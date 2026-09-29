output "instance_id" {
  value = openstack_compute_instance_v2.webapp.id
}

output "instance_name" {
  value = openstack_compute_instance_v2.webapp.name
}

output "floating_ip" {
  value = openstack_networking_floatingip_v2.webapp_fip.address
}
