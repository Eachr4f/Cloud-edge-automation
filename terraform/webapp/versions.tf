terraform {
  required_version = ">= 1.5"

  # Etat conserve hors de l'espace de travail Jenkins : le chemin est fourni
  # par le pipeline (-backend-config="path=...") pour survivre aux nettoyages.
  backend "local" {}

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 1.53.0"
    }
  }
}
