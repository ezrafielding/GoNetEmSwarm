import netifaces
import subprocess
import os


def find_sat_id(net_int):
    for X,ethX in enumerate(net_int):
        if ethX == 'lo':
            continue
        if ethX > 'eth'+str(X):
            print("anomaly detected on interface : " + ethX)
            return(X)
    print("no anomaly detected, assuming missing interface is the last : eth" + str(X+1))
    return(X+1)

#deprecated, my first idea of a network addresse plan that was doomed and fucked up
def set_ip_addr_old(net_int,net_addr,mask):
    for ethX in net_int:
        if ethX == 'lo':
            continue
        int_num = int(ethX[3:])
        dev_addr = str(sat_id)+'.'+str(int_num)
        subprocess.run(['ip','addr','add',net_addr+dev_addr+mask,'dev',ethX])
    print('final network configuration :')
    subprocess.run(['ip','a'])

#This one for sure! I promise you this time it will resolve all network issue, for real for real.
def set_ip_addr_old2(net_int,net_addr,mask):
    for ethX in net_int:
        if ethX == 'lo':
            continue
        int_num = int(ethX[3:])
        min_id = min(sat_id,int_num)
        max_id = max(sat_id,int_num)
        dev_addr = str(max_id)+'.'+str(4*min_id + (2*(max_id==sat_id) + (min_id==sat_id)) )
        subprocess.run(['ip','addr','add',net_addr+dev_addr+mask,'dev',ethX])
    print('final network configuration :')
    subprocess.run(['ip','a'])

#Surely this one will be the last one....
def set_ip_addr_new(net_int,net_addr,mask):
    for ethX in net_int:
        if ethX == 'lo':
            continue
        int_num = int(ethX[3:])
        num_device = (2*(sat_id>int_num) + (sat_id<int_num))
        dev_addr1 = str(int_num)+'.'+str(4*sat_id + num_device)
        dev_addr2 = str(sat_id)+'.'+str(4*int_num + num_device)
        subprocess.run(['ip','addr','add',net_addr+dev_addr1+mask, 'broadcast', '+', 'dev',ethX])
        subprocess.run(['ip','addr','add',net_addr+dev_addr2+mask, 'broadcast', '+', 'dev',ethX])
    print('final network configuration :')
    subprocess.run(['ip','a'])

network_interfaces = netifaces.interfaces()
sat_id = find_sat_id(network_interfaces)
with open("/usr/local/id", 'a') as file:
            file.write(str(sat_id))
net_addr = "172.20."
mask = "/24"
set_ip_addr_new(network_interfaces,net_addr,mask)
