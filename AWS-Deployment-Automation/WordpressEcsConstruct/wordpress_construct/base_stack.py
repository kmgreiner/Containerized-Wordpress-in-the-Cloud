import json
from aws_cdk import (
    core,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_lambda as _lambda,
    aws_efs as efs
)

class WordpressBaseConstructStack(core.Stack):

    def getDBEngine(self,engine):
        if(engine == 'MYSQL'):
            return rds.DatabaseInstanceEngine.MYSQL
        
    def __init__(self, scope: core.Construct, id: str, props, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        #https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_ec2/Vpc.html
        vpc = ec2.Vpc(self, "vpc",
            cidr=props['vpc_CIDR'],
            max_azs=3,
            subnet_configuration=[
                {
                    'cidrMask': 28,
                    'name': 'public',
                    'subnetType': ec2.SubnetType.PUBLIC
                },
                {
                    'cidrMask': 28,
                    'name': 'private',
                    'subnetType': ec2.SubnetType.PRIVATE
                },
                {
                    'cidrMask': 28,
                    'name': 'db',
                    'subnetType': ec2.SubnetType.ISOLATED
                }
            ]
        )

        rds_subnetGroup = rds.SubnetGroup(self, "rds_subnetGroup",
            description = f"Group for {props['environment']}-{props['application']}-{props['unit']} DB",
            vpc = vpc,
            vpc_subnets = ec2.SubnetSelection(subnet_type= ec2.SubnetType.ISOLATED)
        )

        #https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_rds/DatabaseCluster.html
        ##TODO:ADD Aurora Serverless Option
        rds_instance = rds.DatabaseCluster(self,'wordpress-db',
            engine=rds.DatabaseClusterEngine.aurora_mysql(
                version=rds.AuroraMysqlEngineVersion.VER_2_07_2
            ),
            instances=1,
            instance_props=rds.InstanceProps(
                vpc=vpc,
                enable_performance_insights=props['rds_enable_performance_insights'],
                instance_type=ec2.InstanceType(instance_type_identifier=props['rds_instance_type'])
            ),
            subnet_group=rds_subnetGroup,
            storage_encrypted=props['rds_storage_encrypted'],
            backup=rds.BackupProps(
                retention=core.Duration.days(props['rds_automated_backup_retention_days'])
            )
        )

        EcsToRdsSeurityGroup= ec2.SecurityGroup(self, "EcsToRdsSeurityGroup",
            vpc = vpc,
            description = "Allow WordPress containers to talk to RDS"
        )

        #https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_lambda/Function.html
        db_cred_generator = _lambda.Function(
            self, 'db_creds_generator',
            runtime=_lambda.Runtime.PYTHON_3_8,
            handler='db_creds_generator.handler',
            code=_lambda.Code.asset('lambda'),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type= ec2.SubnetType.ISOLATED),        #vpc.select_subnets(subnet_type = ec2.SubnetType("ISOLATED")).subnets ,
            environment={
                'SECRET_NAME': rds_instance.secret.secret_name,
            }
        )

        #Set Permissions and Sec Groups
        rds_instance.connections.allow_from(EcsToRdsSeurityGroup, ec2.Port.tcp(3306))   #Open hole to RDS in RDS SG

        #https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_efs/FileSystem.html
        file_system = efs.FileSystem(self, "MyEfsFileSystem",
            vpc = vpc,
            encrypted=True, # file system is not encrypted by default
            lifecycle_policy = props['efs_lifecycle_policy'],
            performance_mode = efs.PerformanceMode.GENERAL_PURPOSE,
            throughput_mode = efs.ThroughputMode.BURSTING,
            removal_policy = core.RemovalPolicy(props['efs_removal_policy']),
            enable_automatic_backups = props['efs_automatic_backups']
        )

        if props['deploy_bastion_host']:
            #https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_ec2/BastionHostLinux.html
            bastion_host = ec2.BastionHostLinux(self, 'bastion_host',
                vpc = vpc
            )
            rds_instance.connections.allow_from(bastion_host, ec2.Port.tcp(3306))

        self.output_props = props.copy()
        self.output_props["vpc"] = vpc
        self.output_props["rds_instance"] = rds_instance
        self.output_props["EcsToRdsSeurityGroup"] = EcsToRdsSeurityGroup
        self.output_props["file_system"] = file_system
    
    @property
    def outputs(self):
        return self.output_props