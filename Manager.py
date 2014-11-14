import sys
import re
from collections import OrderedDict

from Task import Task
from Resource import Resource
from Instruction import Instruction


# Maps all task IDs to all Task objects
tasks = {}
# Maps task IDs to waiting tasks (in order tasks were told to wait)
waitingTasks = OrderedDict()
# Tasks are placed here when they are freed from waiting
# (makes sure tasks are only processed once per cycle)
readyTasks = []

# Maps resource IDs to Resource objects
resources = {}
# Maps resource IDs to number of units that will be freed
freeBuffer = {}

sysClock = 0;

class ManagerType:
    '''
    Mimic enums
    '''
    OPTIMISTIC = 1
    BANKER = 2


def parseInputData(outline, instructions):
    global tasks, resources # Modify the global variables
    tasks = {x:Task(x) for x in range(1, outline[0] + 1)}

    numResources = outline[1] + 1
    resources = {x:Resource(x, outline[x + 1]) for x in range(1, numResources)}

    pat = re.compile('\w+')
    for item in instructions:
        matches = pat.findall(item)

        command     = matches[0]
        taskID      = int(matches[1])
        delay       = int(matches[2])
        resourceType= int(matches[3])
        numUnits    = int(matches[4])

        ins = Instruction(command, taskID, delay, resourceType, numUnits)
        tasks[taskID].addInstruction(ins)


def isFinished():
    for task in tasks.values():
        if( task.isActive() ):
            return False

    return True


def isDeadlocked():
    '''
    Deadlock if all active tasks are waiting
    '''
    for task in tasks.values():
        if( task.isActive() and not task.isWaiting() ):
            return False

    return not isFinished() # If it's finished, it's not deadlocked


def isSafe(task, instruction):
    '''
    Determines if a given task + instruction leads to a safe state
    (required by the Banker's Algorithm)
    '''
    return True


def getLowestDeadlockedTask():
    '''
    Has to be active, obviously
    '''
    for task in tasks.values():
        if( task.isWaiting() and task.isActive() ):
            return task

    return None


def resolveDeadlock():
    '''
    Abort the lowest numbered deadlocked task (+ free its resources)
    (repeat this process while there's deadlock)
    '''
    while( isDeadlocked() ):
        task = getLowestDeadlockedTask()
        if not task: return

        heldResources = task.getAllResources()
        for rID in heldResources.keys():
            placeIntoFreeBuffer(rID, heldResources[rID])

        del waitingTasks[task.getID()]
        task.abort()

        cleanFreeBuffer()

        for task in tasks.values():
            if task.isActive():
                ins = task.getCurrentInstruction()
                if(ins.getCommand() == "request"):
                    optimisticRequest(task, ins)
                    if( not task.isWaiting() ):
                        task.incInstruction()


def placeIntoFreeBuffer(resourceID, numUnits):
    global freeBuffer

    if( resourceID in freeBuffer.keys() ):
        freeBuffer[resourceID] += numUnits
    else:
        freeBuffer[resourceID] = numUnits


def cleanFreeBuffer():
    global freeBuffer

    for rID in freeBuffer.keys():
        resources[rID].freeUnits(freeBuffer[rID])
        del freeBuffer[rID]


def standardRequest(task, instruction):
    '''
    Fulfills the request if there are available resources
    '''
    if( instruction.getDelay() ):
        instruction.delay -= 1; return

    resource = resources[instruction.getResourceType()]

    if( instruction.getNumUnits() <= resource.getNumAvailable() ):
        task.stopWaiting() # Freed from waiting when request can be satisfied
        readyTasks.append(task) # Note that tasks were "readified" on this cycle

        if task.getID() in waitingTasks: # Leave the waiting tasks
            del waitingTasks[task.getID()]
            #print("Task :" + str(task.getID()) + " left the waiting queue!")

        # The request can be fulfilled
        if( resource.takeUnits(instruction.getNumUnits()) ):
            task.grantResource(resource.getID(), instruction.getNumUnits())
            #print( "Task :" + str(task.getID()) + " fulfilled request")

    else:
        #print("Task :" + str(task.getID()) + " request cannot be granted!")
        task.wait() # Wait until resources become available
        if not task.getID() in waitingTasks: # Enter the waiting tasks
            waitingTasks[task.getID()] = task
            #print("\tWent into the queue!")


def bankerRequest(task, instruction):
    '''
    Wrapper around standardRequest() that proceeds only if the state is safe
    '''
    if( isSafe(task, instruction) ):
        # Guaranteed that it won't have to wait
        standardRequest(task, instruction)
    else:
        task.wait() # Wait until resources become available
        if not task.getID() in waitingTasks: # Enter the waiting tasks
            waitingTasks[task.getID()] = task


def bankerProcessClaims(task, initInstruction):
    '''
    Aborts task if it's asking for unknown resources or way too many units
    '''
    rType = initInstruction.getResourceType()
    rUnits = initInstruction.getNumUnits()

    if( not rType in resources.keys()
        or rUnits > resources[rType].getTotUnits() ):
        task.abort()
        print("task aborted in the beginning... asked for too much")
    else:
        task.setClaims(rType, rUnits)


def execute(manager, task, instruction):
    if( instruction.getDelay() ):
        instruction.delay -= 1; return

    if( instruction.getCommand() == "initiate" and
        manager is ManagerType.BANKER ):
        bankerProcessClaims(task, instruction)

    if( instruction.getCommand() == "request" ):
        if( manager is ManagerType.OPTIMISTIC ):
            standardRequest(task, instruction)

        elif( manager is ManagerType.BANKER ):
            bankerRequest(task, instruction)


    elif( instruction.getCommand() == "release" ):
        resource = resources[instruction.getResourceType()]

        # Fulfill the release (place items into freeBuffer)
        if( instruction.getNumUnits() <= resource.getNumBusy() ):
            placeIntoFreeBuffer(resource.getID(), instruction.getNumUnits())
            task.releaseResource(resource.getID(), instruction.getNumUnits())
            #print("Task :" + str(task.getID()) + " fulfilled release (" + str(instruction.getNumUnits()) + " units)")

    # Carry on and determine stats
    if( not task.isWaiting() ):
        task.incInstruction()
        if task.isFinished():
            task.clockEndTime(sysClock)
    else:
        task.incWaitingTime()


def run(manager):
    global sysClock

    while not isFinished():
        global readyTasks

        # Process blocked tasks in the order they were told to wait
        for task in waitingTasks.values():
            if task.isActive(): # Should be all
                ins = task.getCurrentInstruction()
                execute(manager, task, ins)

        # Process non-blocked tasks
        for task in tasks.values():
            if( task.isActive() and not task.isWaiting()
                and not task in readyTasks ):
                ins = task.getCurrentInstruction()
                execute(manager, task, ins)

        readyTasks = [] # Reset ready tasks

        # Check if there's deadlock (applies to optimistic manager)
        if( manager is ManagerType.OPTIMISTIC and isDeadlocked() ):
            resolveDeadlock()

        cleanFreeBuffer()
        sysClock += 1


def printReport():
    for task in tasks.values():
        if task.isAborted():
            print("aborted -- no stats"); continue

        print("Task #" + str(task.getID()) + "\n")
        print("\tRunning: " + str(task.getStats()['running']) + "\n")
        print("\tWaiting: " + str(task.getStats()['waiting']) + "\n")


if __name__ == "__main__":
    filePath = "inputs/input-13.txt"
    file = file(filePath, 'r')

    outline = [int(s) for s in file.readline().split()]
    instructions = re.findall(r'[a-z]+\s+[\d\s]+', file.read())

    parseInputData(outline, instructions)
    print(str(resources))

    run(ManagerType.BANKER)

    printReport()
