provider "openstack" {
  auth_url            = var.auth_url
  user_name           = var.os_user_name
  password            = var.os_password
  tenant_name         = var.os_project_name
  user_domain_name    = var.os_user_domain_name
  project_domain_name = var.os_project_domain_name
  region              = var.os_region
}
