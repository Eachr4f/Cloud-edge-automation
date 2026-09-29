resource "openstack_compute_instance_v2" "webapp" {
  name            = var.instance_name
  image_name      = var.image_name
  flavor_name     = var.flavor_name
  key_pair        = var.key_pair_name
  security_groups = [var.security_group]

  network {
    name = var.network_name
  }
}

resource "openstack_networking_floatingip_v2" "webapp_fip" {
  pool = "public"
}

resource "openstack_compute_floatingip_associate_v2" "webapp_fip_assoc" {
  floating_ip = openstack_networking_floatingip_v2.webapp_fip.address
  instance_id = openstack_compute_instance_v2.webapp.id
}
