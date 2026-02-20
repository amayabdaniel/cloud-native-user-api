resource "aws_security_group" "aurora" {
  name_prefix = "${var.name}-aurora-"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.eks_node_sg_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

module "aurora" {
  source  = "terraform-aws-modules/rds-aurora/aws"
  version = "~> 10.0"

  name           = var.name
  engine         = "aurora-postgresql"
  engine_version = var.engine_version
  master_username = var.master_username
  database_name   = var.database_name

  manage_master_user_password = true

  vpc_id               = var.vpc_id
  db_subnet_group_name = var.db_subnet_group_name
  create_security_group  = false
  vpc_security_group_ids = [aws_security_group.aurora.id]

  storage_encrypted   = true
  apply_immediately   = true
  skip_final_snapshot = true

  serverlessv2_scaling_configuration = {
    min_capacity = var.min_capacity
    max_capacity = var.max_capacity
  }

  cluster_instance_class = "db.serverless"
  instances = {
    one = {}
  }

  tags = var.tags
}
