resource "openstack_compute_instance_v2" "centos_vm" {
  name            = "centos-terraform"
  image_name      = "CentOS-Terraform"
  flavor_name     = "m1.centos"
  key_pair        = var.key_pair_name
  security_groups = [var.security_group]

  network {
    name = var.network_name
  }
}

resource "openstack_networking_floatingip_v2" "centos_fip" {
  pool = "public"
}

resource "openstack_compute_floatingip_associate_v2" "centos_fip_assoc" {
  floating_ip = openstack_networking_floatingip_v2.centos_fip.address
  instance_id = openstack_compute_instance_v2.centos_vm.id
}
