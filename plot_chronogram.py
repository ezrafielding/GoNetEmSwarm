import matplotlib.pyplot as plt
import argparse
import numpy as np
import csv
import os


def add_entry(journal, event):
    journal['lTime'].append(float(event['Local Time']))
    journal['evType'].append(event['Event'])
    journal['withNode'].append(event['Node Name'])
    journal['msgType'].append(int(event['Message Type']))
    journal['msgSender'].append(event['Message Sender'])
    journal['msgCount'].append(int(event['Message Counter']))
    journal['msgPload'].append(event['Message Payload'])
    journal['treated'].append(False)


def readjournal(Journal, journame:str, path, prefix, suffix, no_gnd):
    full_path = os.path.join(path, journame)
    with open(full_path, 'r') as csvfile:
        csvreader = csv.DictReader(csvfile, delimiter='|')
        node_name=journame[len(prefix)-3*no_gnd:-len(suffix)]
        Journal[node_name] = {
            "Global":{"lTime":[], "evType":[], "withNode":[], "msgType":[], "msgSender":[], "msgCount":[], "msgPload":[], "treated":[] },
            "Unicast":{"lTime":[], "evType":[], "withNode":[], "msgType":[], "msgSender":[], "msgCount":[], "msgPload":[], "treated":[]  },
            "RBcast":{"lTime":[], "evType":[], "withNode":[], "msgType":[], "msgSender":[], "msgCount":[], "msgPload":[], "treated":[]  },
            "SBcast":{"lTime":[], "evType":[], "withNode":[], "msgType":[], "msgSender":[], "msgCount":[], "msgPload":[], "treated":[]  },
            "Tree":{"lTime":[], "evType":[], "withNode":[], "msgType":[], "msgSender":[], "msgCount":[], "msgPload":[], "treated":[]  },
            "EarthToSwarm":{"lTime":[], "evType":[], "withNode":[], "msgType":[], "msgSender":[], "msgCount":[], "msgPload":[], "treated":[]  }
            }
        for event in csvreader:
            add_entry(Journal[node_name]["Global"], event)
            match event['Message Type']:
                case '0':
                    add_entry(Journal[node_name]["Unicast"], event)
                case '1':
                    add_entry(Journal[node_name]["RBcast"], event)
                case '2':
                    add_entry(Journal[node_name]["SBcast"], event)
                case '8':
                    add_entry(Journal[node_name]["Tree"], event)
                case '9':
                    add_entry(Journal[node_name]["EarthToSwarm"], event)
                case _:
                   print("Unknown message type, the message : " + str(event))
                   print("Can\'t be parsed.")



def draw_baseline(axes, sat_name, journal, no_gnd):
    offset = journal["offset"]
    # The baseline.
    axes.axhline(offset, color='black')
    n = len(journal['lTime'])+2
    plt.text(-0.02, offset-0.05, sat_name, fontsize=15)
    journal['xcoord'] = [ (j+1)/n for j in range(len(journal['lTime']))]
    axes.plot(journal['xcoord'], np.ones_like(journal['lTime'])*offset, "ko", mfc="white")

    # Annotate the lines.
    for x, nwith in zip( journal['xcoord'], journal["withNode"]):
        axes.annotate("gnd" if (no_gnd and nwith=="gnd") else "", xy=(x, offset),
                    xytext=(-3, 3), textcoords="offset points",
                    verticalalignment="bottom" ,#if mcount%2 == 0 else "top",
                    weight="normal",
                    bbox=dict(boxstyle='square', pad=0, lw=0, fc=(1, 1, 1, 0.7))
                    )

def draw_recep(axes, journalA, nameA, journalB, nameB):
    for i in range(len(journalA['lTime'])):
        message_idA = journalA['msgSender'][i]+str(journalA['msgCount'][i])
        if journalA["treated"][i]:
            continue
        if not (journalA['withNode'][i]==nameB or journalA['withNode'][i]=="gnd"):
            continue
        if (journalA['evType'][i]=='RCV' or journalA['evType'][i]=='DMP'):
            for j in range(len(journalB['lTime'])):
                if journalB["treated"][j]:
                    continue
                message_idB = journalB['msgSender'][j]+str(journalB['msgCount'][j])
                if message_idA == message_idB:
                    if (journalB['withNode'][j]==nameA and (journalB['evType'][j]=='SNT' or journalB['evType'][j]=='TRA') ):
                        if (journalA['evType'][i]=='RCV'):
                            lineStyle="-"
                            lineColor="black"
                        if (journalA['evType'][i]=='DMP'):
                            lineStyle="--"
                            lineColor="grey"
                        axes.annotate('',
                                    xytext=(journalA['xcoord'][i],journalA['offset']),
                                    xy=(journalB['xcoord'][j], journalB['offset']),
                                    arrowprops=dict(arrowstyle="<-",
                                                    ls=lineStyle,
                                                    color=lineColor)
                                    )
                        journalB["treated"][j] = True
                        journalA["treated"][i] = True
                        break

def create_chronogram(title_chrono, typeToPlot, no_gnd):

    path="shared/logs/"
    prefix="journal_"+no_gnd*"sat"
    suffix=".log"
    Journal = {}

    for file in sorted(os.listdir(path), reverse=True):
        filename = os.fsdecode(file)
        if filename.endswith(suffix) and filename.startswith(prefix):
            readjournal(Journal, filename, path, prefix, suffix, no_gnd)
        else:
            continue


    fig, ax = plt.subplots(figsize=(8.8, 7), layout="constrained")
    # The figure and the axes.
    ax.set(title=title_chrono)
    ax.spines[["left", "top", "bottom", "right"]].set_visible(False)
    ax.yaxis.set_visible(False)
    ax.xaxis.set_visible(False)

    for idn,node_name in enumerate(Journal.keys()):
        Journal[node_name][typeToPlot]["offset"]=idn*2
        draw_baseline(ax, node_name, Journal[node_name][typeToPlot], no_gnd)

    for nodeR in Journal.keys():
        for nodeE in Journal.keys():
            if nodeR == nodeE :
                continue
            else:
                draw_recep(ax, Journal[nodeR][typeToPlot], nodeR,Journal[nodeE][typeToPlot], nodeE)

    plt.show()


MSG_TYPE_CHOICES = [
    "Global", "Unicast", "RBcast", "SBcast", "Tree", "EarthToSwarm"
]

parser = argparse.ArgumentParser(
    description="Generate a Chronogram from ./shared/logs/journal_(sat/gnd)[0-9]*.log",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=__doc__,
)
parser.add_argument("--name", "-n", type=str, default="Chronogram",
    dest="title_chrono",
    help="graphic title (default: Chronogram)")
parser.add_argument("--type-to-plot", "-t", choices=MSG_TYPE_CHOICES, default="Global",
    dest="type_to_plot",
    help="Which type of message would you like to include in the chronograph? (default: Global (all messages))")
parser.add_argument("--ground-station", "-g", type=bool, default=False,
    dest="ground_station",
    help="Would you like to includ the ground stations in the chronogram (default: False)")

args = parser.parse_args()

# ---- resolve edges and node count from graph file if provided -----------
print(f"Generating {args.title_chrono} Chronograme, tracking {args.type_to_plot} messages.")
create_chronogram(args.title_chrono, args.type_to_plot, not args.ground_station)
