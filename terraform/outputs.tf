output "instance_id" {
  value = openstack_compute_instance_v2.centos_vm.id
}

output "instance_status" {
  value = openstack_compute_instance_v2.centos_vm.power_state
}

output "floating_ip" {
  value = openstack_networking_floatingip_v2.centos_fip.address
}
