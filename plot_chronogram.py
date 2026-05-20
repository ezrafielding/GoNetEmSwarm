import matplotlib.pyplot as plt
import numpy as np
import csv
import os

path="shared/logs/"
prefix="journal_"
suffix=".log"

def readjournal(journame:str):
    full_path = os.path.join(path, journame)
    with open(full_path, 'r') as csvfile:
        csvreader = csv.DictReader(csvfile, delimiter='|')
        sat_id=journame[len(prefix):-len(suffix)]
        Coms[journame] = {'myAd':"10.255.0."+sat_id,'Ltime': [],'MsgCount':[],'pload':[],'sender':[],'evTyp':[], 'ipAd':[], 'name':"sat"+sat_id}
        for event in csvreader:
            ################################################################################################
            #MODIFY THE if event[' Message Type '] == ' 8 ': CONDITION IF YOU WANT TO HANDLE OTHER MESSAGES#
            ################################################################################################

            if event['Message Type'] == '1':
                Coms[journame]['Ltime'].append(float(event['Local Time']))
                Coms[journame]['MsgCount'].append(int(event['Message Counter']))
                Coms[journame]['ipAd'].append(event['Ip Address'])
                Coms[journame]['pload'].append(event['Message Payload'])
                Coms[journame]['sender'].append(event['Message Sender'])
                Coms[journame]['evTyp'].append(event['Event'])

def draw_baseline(axes, sat):
    offset = Coms[sat]["offset"]
    # The baseline.
    axes.axhline(offset, color='black')
    n = len(Coms[sat]['Ltime'])+2
    plt.text(-0.02, offset-0.05, Coms[sat]["name"], fontsize=15)
    Coms[sat]['xcoord'] = [ (j+1)/n for j in range(len(Coms[sat]['Ltime']))]
    axes.plot(Coms[sat]['xcoord'], np.ones_like(Coms[sat]['Ltime'])*offset, "ko", mfc="white")

    # Annotate the lines.
    for x, mcount, pload in zip( Coms[sat]['xcoord'], Coms[sat]['MsgCount'], Coms[sat]["pload"]):
        axes.annotate(find_request_type(pload), xy=(x, offset),
                    xytext=(-3, 3), textcoords="offset points",
                    verticalalignment="bottom" ,#if mcount%2 == 0 else "top",
                    weight="normal",
                    bbox=dict(boxstyle='square', pad=0, lw=0, fc=(1, 1, 1, 0.7)))


def find_request_type(pload):
    ################################################################################################
    #         MODIFY THIS FUNCTION TO CHANGE THE ANNOTATION ON TOP OF THE MESSAGES EVENTS          #
    ################################################################################################
    if "None" in pload:
        return "Query"
    if "Reject" in pload:
        return "Reject"
    if "Adopted" in pload:
        return "Adopted"
    if "Rooted" in pload:
        return "Rooted"
    return "Ukn"


def draw_recep(axes, satA, satB):
    for i in range(len(Coms[satA]['Ltime'])):
        message_idA = Coms[satA]['sender'][i]+str(Coms[satA]['MsgCount'][i])
        if Coms[satA]['evTyp'][i]=='RCV':
            for j in range(len(Coms[satB]['Ltime'])):
                message_idB = Coms[satB]['sender'][j]+str(Coms[satB]['MsgCount'][j])
                if message_idA == message_idB:
                    if Coms[satB]['ipAd'][j]==Coms[satA]["myAd"]:
                        axes.annotate('',
                                      xytext=(Coms[satA]['xcoord'][i],Coms[satA]['offset']),
                                      xy=(Coms[satB]['xcoord'][j], Coms[satB]['offset']),
                                      arrowprops=dict(arrowstyle="<-")
                                      )


Coms = {}

for file in os.listdir(path):
    filename = os.fsdecode(file)
    if filename.endswith(suffix) and filename.startswith(prefix):
        readjournal(filename)
    else:
        continue


fig, ax = plt.subplots(figsize=(8.8, 7), layout="constrained")
# The figure and the axes.
ax.set(title="Tree related TimeLine")
ax.spines[["left", "top", "bottom", "right"]].set_visible(False)
ax.yaxis.set_visible(False)
ax.xaxis.set_visible(False)
for idj,journal in enumerate(Coms.keys()):
    Coms[journal]["offset"]=idj*2
    draw_baseline(ax, journal)

for satR in Coms.keys():
    for satE in Coms.keys():
        if satR == satE :
            continue
        else:
            draw_recep(ax, satR, satE)

plt.show()
