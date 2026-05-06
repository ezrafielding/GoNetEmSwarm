# What do you need to know to use tranceiver.py :

## New Stuff :

### Normal Broadcast with tranceiver_tree :
If you use a tranceiver_tree, you have acess to broadcast thanks to self.send_tree_broadcast(paylod: dict) It works the same way as the reliable broadcast, except it take much less messages.
But  for Ittowork properly, tree needs to be finished before sending the message (at least locally for the sender node). If tree isn't finished, an UnfinishedTreeException is raised.

### Chronogram plotting with plot_chronogram.py :
more info at the end of the readme

### Tranceiver_queue :
A new version of tranceiver wich now support a message queue.
When calling backend message_handler on a packet, you can raise the NotReady exception, in wich case message won't be delivered, will be sent at the back of the queue letting other messages to be handled in the meantime.
Not really usefull rn, but it is a start for future more complexe message passing implementation like FIFO or Causal

## Messages :
Messages are dictionaries with the following items :
- "type":int (0:Unicast 1:Reliable_Broadcast 2:Simple_Broadcast (only implemented with spaning tree rn) 3-5:Placeholder 6:HeartBeat 7:Ready (6&7 Only used for backend network readyness detection, no use in proper algorithms). 8:Messages related to tree creation)
- "sender":str (IP address of the loopback interface of the node from wich the message originated.)
- "counter":int (message counter for message indentification purpose.)
- "payload":dict (user defined part of the message, where the data needed for algorithms are stocked)

## How to send message :
### Reliable Broadcast :
Thanks to the self.send_broadcast(payload: dict) method.
Reliable => use a big amount of message to communicate (~2*n where n is the number of links in the network graph) but ensure that every node in the same connected graph as the sender will get the message.

### Unicast :
Thanks to the self.send_unicast(payload: dict, addr:str) method. (addr is the loopback ip of the node you want to send the message to.)
With big Networks (About >= 100 Nodes) I am experimenting some message losses, I think that furthest away nodes pair are to far away to reach each others due to short TTL(Time To Live) of packets.

## How to implement your own algorithms :
1 - Implement your algorithm by overriding the on_message() function of tranceiver wich will be called every time a message is received by the node.
```python 
 def on_message(self, data: dict, addr: tuple):
        if (data["type"] <= 1): #Only react to interesting messages, not the internal ones used to detect starting of network
            do_something()
```
2 - Start the backend network service thanks to the self.start() method from tranceiver.
/!\ It is crucial to ensure that the whole network is ready to send/receive/transmit message before starting the algorithm. At least before sending the first message. /!\
To do so, please use self.network_initialized:boolean False at start, become True when the network is completly initialized (something like this:
```python 
while(not algorithm.network_initialized):
    time.sleep(1)
```
3 - Ensure that the backend network service of each node don't end prematurely. Or else it stop fowarding broadcast and that is likely to affect the proper functioning of the other nodes.
The simplest way is probably to add a while(True) at the end of your code. If the algorithm is easy enough so each node can know when it is finished you can also chek for that.

*TLDR think simple_unicast.py is a great exemple wich basically use every features. You can do it*

## Evaluate results :
You can either do your own logging or use the already existent ones:
- Detailed "readable" logging for debug and troubleshoting containing some exception can be found in shared/logs/network/trans_{sat_name}.log 
- A list of every message related event (RCV: message received, SNT: message sent, TRA: message transmitted) with their local timestamp is automatically generated in the shared/logs/journal_{sat_name}.log
please note that there is no global time measure, only local time. (As global time is kinda irrelevant in our context)
- The script plot_chronogram.py read journals entry and represent them in a chrornogram format, much more readable, with every nodes on the same figure. Rn it in probably not pretty enough to be used in a regular paper, but It can still help for debugging purpose
it looks like this : 
  ![mono_tree_full_mesh_5.png]
## Most important :
I recently stumbled a lot because I wasn't aware that in the current model, communication isn't FIFO. please beware of that (a FIFO version is comming soon)
If you got any issues, I am probably not very far away, don't hesitate to reach out to me !

