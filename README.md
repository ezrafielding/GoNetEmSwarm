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
## Right now, I am using a static address plan that assume a strongly connected topology
## .tools/run_algorithme.sh is an extension of run_algorithme.sh from ConSwarm, able to handle both ConSwarm and GoNetEmSwarm
