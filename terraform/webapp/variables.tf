variable "auth_url" {
  description = "Point d'entree Keystone (API de DevStack)"
  type        = string
  default     = "http://192.168.56.10/identity/v3"
}

variable "os_user_name" {
  type    = string
  default = "admin"
}

variable "os_password" {
  description = "Mot de passe admin OpenStack (fourni par TF_VAR_os_password, depuis un credential Jenkins)"
  type        = string
  sensitive   = true
}

variable "os_project_name" {
  type    = string
  default = "admin"
}

variable "os_user_domain_name" {
  type    = string
  default = "Default"
}

variable "os_project_domain_name" {
  type    = string
  default = "Default"
}

variable "os_region" {
  type    = string
  default = "RegionOne"
}

variable "instance_name" {
  type    = string
  default = "webapp-vm"
}

variable "image_name" {
  type    = string
  default = "ubuntu-24.04"
}

variable "flavor_name" {
  description = "Flavor legere (1 Go de RAM) : m1.web"
  type        = string
  default     = "m1.web"
}

variable "key_pair_name" {
  type    = string
  default = "mykey"
}

variable "network_name" {
  type    = string
  default = "private"
}

variable "security_group" {
  type    = string
  default = "web-sg"
}
