# Compatibility tool for using ConSwarm with GoNetEm
to use this 3 steps are required :
1 - Build docker image of a test satellite (satestellite) with 
```bash
sudo bash buildimage.sh
```
1 - Configure and start GoNetEm serveur :
Verifie that config.yaml exist and contains precedent image declaration(look like this):
```yaml
  extraNodes:
  - type: satellite
    image: tivadarofthorns/satestellite:0.4.0
```
Then start serveur with 
```bash
sudo bash startserveur.sh
```
Your terminal will now be busy with GoNetEm server.
So you need to start another one to use the console to monitor GoNetEm.
## Right now, I am using a static address plan that assume a strongly connected topology.
## Also, for static address attribution to work properlys, please ensure that .gnet project look like this :
```yaml
nodes:
  sat1:
    type: docker.satellite
  sat2:
    type: docker.satellite
  sat3:
    type: docker.satellite
links:
  - peer1: sat1.2
    peer2: sat2.1
  - peer1: sat1.3
    peer2: sat3.1
  - peer1: sat2.2
    peer2: sat3.3
```
It is important that each network interface bear the number of the satellite it is linked to.
*I probably need to find a way for it to be more robust, maybe osbf routing can resolve this issue*
## .tools/run_algorithme.sh is an extension of run_algorithme.sh from ConSwarm, able to handle both ConSwarm and GoNetEmSwarm
