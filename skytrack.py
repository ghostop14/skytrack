#!/usr/bin/python3

###################################################################
#
# Application: skytrack.py
# Author: ghostop14
#
# This script will calculate relative azimuth and elevation of a celestial body based on the skyfield
# python library.  This covers planets and moons within our solar system in the implemented version here.
#
# The script can also control a radio via GQRX's remote control or SDRSharp with the netremote plugin.
# Rotor control is also being integrated via rotctl.
##################################################################

# -----------------------imports -------------------------------------
import argparse
import socket
import time
import subprocess
from datetime import datetime
from datetime import timedelta
from tzlocal import get_localzone
from dateutil import parser
import pytz

from skyfield.api import load,Topos
from skyfield import almanac
from skyfield.nutationlib import iau2000b

netPortRotor = None
netPortFreq = None
lastElevation=-999.0

# -------------------  Global Functions ----------------------------------------
def socketConnect(server, port):
    global netPortRotor
    
    if not netPortRotor:
        netPortRotor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            netPortRotor.connect((server, port))
        except:
            print("Rotor Error connecting to " + server + ":" + str(port))
            netPortRotor = None
            
def targetUpAt(observer,target):
    topos_at = observer.at
    def is_target_up_at(t):
        """Return `True` if the target has risen by time `t`."""
        t._nutation_angles = iau2000b(t.tt)
        return topos_at(t).observe(target).apparent().altaz()[0].degrees > -0.8333
    is_target_up_at.rough_period = 0.5  # twice a day
    return is_target_up_at

def doppler_shift(frequency, relativeVelocity):
    """
    DESCRIPTION:
        This function calculates the doppler shift of a given frequency when actual
        frequency and the relative velocity is passed.
        The function for the doppler shift is f' = f - f*(v/c).
    INPUTS:
        frequency (float)        = satlitte's beacon frequency in Hz
        relativeVelocity (float) = Velocity at which the satellite is moving
                                   towards or away from observer in m/s
    RETURNS:
        Param1 (float)           = The frequency experienced due to doppler shift in Hz
    AFFECTS:
        None
    EXCEPTIONS:
        None
    DEPENDENCIES:
        ephem.Observer(...), ephem.readtle(...)
    Note: relativeVelocity is positive when moving away from the observer
          and negative when moving towards
    """
    return  (frequency - frequency * (relativeVelocity/3e8)) 

def RCmoveToPosition(port, controllerType, baud,  azimuth, elevation):
        # Port can be /dev/ttyUSB0 type of port, or:
        # <ip>:<port>
        
        if azimuth < 0.0 or azimuth > 360.0:
            return -1 

        if elevation < 0:
            elevation = 0
            
        if elevation > 360:
            return -1 

        # -m is type, type 2 is hamlib compatible, 1401 is Celestron/Nextar.  man rotctl can provide a better overview
        if ':' in port:
            # Network connection.  rotctl sends a lot of extra dump_states.  So let's do it by hand.
            # cmd = [ 'rotctl' , '-m' , str(controllerType) , '-r' , str(port), 'P', str(azimuth) , str(elevation) ]
            if not netPortRotor:
                params = port.split(":")
                socketConnect(params[0], int(params[1]))
                
            if netPortRotor:
                cmdString = "P " + str(azimuth) + " " + str(elevation) + "\n"
                netPortRotor.send(cmdString.encode('utf-8'))
                
            return 0
        else:
            cmd = [ 'rotctl' , '-m' , str(controllerType) , '-r' , str(port), '-s',str(baud),'P', str(azimuth), str(elevation) ]
            
            try:
                cpval = subprocess.run(cmd,timeout=2,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                
                if cpval.returncode == 0:
                    return 0 
                else:
                    # Note: unable to connect to port is returncode 2
                    rotorResult = cpval.stdout.decode('ASCII')
                    print('ROTOR ERROR: ')
                    print(rotorResult)
                    
                    return cpval.returncode
            except subprocess.TimeoutExpired as e:
                return -3
            except subprocess.CalledProcessError as e:
                return -4

# ----------------------  Main Code -------------------------------------------------------

if __name__ == '__main__':
    argparser = argparse.ArgumentParser(description='Solar System Planet/Moon Tracker')
    argparser.add_argument('--body', help="[Required] Planet/Moon from the skyfield library to track.  Use --listbodies to see options.", default="")
    argparser.add_argument('--lat', help="[Required] Observer Latitude", default=-999.0)
    argparser.add_argument('--long', help="[Required] Observer Longitude", default=-999.0)
    argparser.add_argument('--listbodies', help="List options for the --body parameter", default=False, action='store_true')

    argparser.add_argument('--freq', help="If provided, a doppler shift will be calculated", default=0.0, required=False)
    argparser.add_argument('--radio', help="If provided, gqrx/gpredict-compatible frequency control commands will be sent to the specified host:port (Note: This disables any value in the --date parameter and the --freq parameter is required and causes the program to continue to loop, sending updates)", default="", required=False)
    argparser.add_argument('--send-aos-los', help="Send AOS/LOS messages to radio above the specified elevation (Default is not to send)", default=False, action='store_true', required=False)
    argparser.add_argument('--aos-elevation', help="Set the AOS/LOS elevation boundary in degrees (Default is 10 degrees)", default=10.0, required=False)
    argparser.add_argument('--sdrsharp', help="If provided, frequency control commands will be sent the NetRemote plugin for SDRSharp on the specified host:port (Note: This disables any value in the --date parameter and the --freq parameter is required and causes the program to continue to loop)", default="", required=False)
    argparser.add_argument('--delay', help="Time in seconds between radio and rotor updates (default=30 seconds)", default=30, required=False)
    argparser.add_argument('--rotor', help="HamLib compatible rotor control (matches gpredict rotor/rotctl).  Can be <ip>:<port> or device like /dev/ttyUSB0", default="", required=False)
    argparser.add_argument('--rotortype', help="rotctl rotor type (use rotctl -l to show numbers).  Default is 2 (hamlib/net), Celestron is 1401, SPID is 901 or 902 depending on mode.", default=2, required=False)
    argparser.add_argument('--rotorbaud', help="If needed, can provide a rotor baud.  Default is 9600", default=9600, required=False)
    argparser.add_argument('--rotorleftlimit', help="If needed, can provide a rotor 'left' limit in degrees. For instance if obstructions block rotation or view.  Default is no restriction.  Note: if either left/right limit is noted, both are required.", default=-1, required=False)
    argparser.add_argument('--rotorrightlimit', help="If needed, can provide a rotor 'right' limit in degrees. For instance if obstructions block rotation or view.  Default is no restriction. Note: if either left/right limit is noted, both are required.", default=-1, required=False)
    argparser.add_argument('--rotorelevationlimit', help="If needed, can provide a rotor 'elevation' limit in degrees. For instance if obstructions block rotation or view.  Default is 90 degrees (straight up).", default=-1, required=False)
    argparser.add_argument('--utcdate', help="[Alternate date] If provided, the UTC date and time will be used for the rise/set calculation rather than the current date/time.  Format: year/month/day hh:mm:ss", default="", required=False)

    # Load data files
    planets=load('de421.bsp')
    ts = load.timescale()
    
    # Parse Args
    args = argparser.parse_args()

    # Check if this is just a listbodies call:
    if args.listbodies:
        bodyNames = planets.names()
        printedNames=[]
        
        for curKey in bodyNames:
            curSet = bodyNames[curKey]
            
            for curObject in curSet:
                printedNames.append(str(curObject))
        
        # Now sort for printing
        sortedNames = sorted(printedNames)
            
        for curName in sortedNames:
            print(curName)
        
        exit(0)
        
    # Check we have the parameters we need:
    if len(args.body) == 0:
        print("ERROR: Body is required.")
        exit(1)
        
    if (args.lat==-999.0 or args.long==-999.0):
        print("ERROR: Latitude and Longitude are required.")
        exit(1)

    aos_elevation = float(args.aos_elevation)
    planetaryBody=args.body
    # Get object descriptors
    earth = planets['earth']
    
    try:
        target = planets[planetaryBody]
    except Exception as e:
        try:
            # May be barycenter (center of mass of orbiting bodies.  e.g. saturn is like this in the db file.
            planetaryBody = planetaryBody + ' barycenter'
            target = planets[planetaryBody]
        except:
            print('ERROR: Unknown body: ' + planetaryBody)
            print(str(e))
            exit(1)
        
    datestr = args.utcdate.strip('"')
    datestr = datestr.strip("'")
    delay= int(args.delay)

    host="127.0.0.1"
    port=7356
    useRadio = False
    firstTime = True

    if len(args.rotor) > 0:
        useRotor = True
    else:
        useRotor = False
        
    RADIOTYPE_GQRX = 1
    RADIOTYPE_SDRSHARP = 2

    radioType = RADIOTYPE_GQRX
    radioCommand = "F <frequency>\n"
    #BUFFER_SIZE=7
    BUFFER_SIZE=7

    radio = args.radio
    
    if len(radio) > 0:
        radioType = RADIOTYPE_GQRX

    if len(args.sdrsharp) > 0:
        radio = args.sdrsharp
        radioType = RADIOTYPE_SDRSHARP
        BUFFER_SIZE=200
        radioCommand='{"Command": "Set", "Method": "Frequency","Value": <frequency>}'
        
    if len(radio) > 0:
        if args.freq == 0.0:
            print("ERROR: a frequency must be provided in radio mode.")
            exit(1)

        useRadio = True
        hostparams=radio.split(":")
        host=hostparams[0]
        if len(hostparams) > 1:
            port=int(hostparams[1])

        # Now let's see if we can connect:
        if not netPortFreq:
            netPortFreq = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
            try:
                netPortFreq.connect((host, port))
                netPortFreq.settimeout(0.5)
            except Exception as e:
                netPortFreq = None
                print("ERROR: Unable to connect to radio at " + args.radio + ". Error: " + str(e))

    if ((args.rotorleftlimit != -1 and args.rotorrightlimit == -1) or
        (args.rotorleftlimit == -1 and args.rotorrightlimit != -1)):
        print("ERROR: if one limit is provided, both left/right must be set.")
        exit(2)
        
    if args.rotorleftlimit > 360.0 or (args.rotorleftlimit < 0.0 and args.rotorleftlimit != -1):
        print("ERROR: bad limit value.")
        exit(2)
        
    if args.rotorrightlimit > 360.0 or (args.rotorrightlimit < 0.0 and args.rotorrightlimit != -1):
        print("ERROR: bad limit value.")
        exit(2)
        
    if args.rotorleftlimit != -1 and args.rotorrightlimit != -1:
        usingRotorLimits = True
        
        # Depending on where your target is, left/right could span 0 degrees.  In that scenario,
        # the left limit will be greater than the right limit (e.g. 330 degrees left, 30 degrees right)
        if args.rotorleftlimit <= args.rotorRightLimit:
            rotorLimitsReversed = False
        else:
            rotorLimitsReversed = True
    else:
        usingRotorLimits = False
        rotorLimitsReversed = False
        
    # Calculate observer's position
    topoPosition = Topos(float(args.lat), float(args.long))
    observer = earth + topoPosition

    if len(datestr) > 0:
        targetTime = parser.parse(datestr)
        t = ts.utc(targetTime.year, targetTime.month,  targetTime.day,  targetTime.hour, targetTime.minute, targetTime.second)
    else:
        t = ts.now()
        targetTime = datetime.now()
        
    deltaT = 10
    
    try:
        while (firstTime or useRadio or useRotor):
            firstTime = False

            now = datetime.now()
            utcnow = datetime.utcnow()
            
            print("\nCurrent Time: " + now.strftime("%m/%d/%Y %H:%M:%S") + "  (" + utcnow.strftime("%m/%d/%Y %H:%M:%S") + " UTC)")
            if len(datestr) > 0:
                print("Calculating for: " + datestr + " UTC")
 
            print('Target: ' + args.body)
            
            # For the radio, we're using real time
            if useRadio or useRotor:
                t = ts.now()
                targetTime = datetime.now()

            astrometric = observer.at(t).observe(target)
            elevationTmp, azimuthTmp, dist_AU = astrometric.apparent().altaz()

            azimuth = azimuthTmp.to('deg').value
            elevation = elevationTmp.to('deg').value
            distance_meters = dist_AU.to("m").value
            distance=dist_AU.to("m").value*0.00062137

            futureTime = t.utc_datetime()
            futureTime = futureTime + timedelta(seconds=int(deltaT))

            futureT = ts.utc(futureTime.year, futureTime.month,  futureTime.day,  futureTime.hour, futureTime.minute, futureTime.second)
            astrometricFuture = observer.at(futureT).observe(target)
            elevationTmp, azimuthTmp, dist_AU = astrometricFuture.apparent().altaz()
            futureDistance = dist_AU.to("m").value
            
            # This will calculate in m/s
            # moon - moonFuture will produce the correct sign, - for towards, + for away
            relativeVelocity=(futureDistance - distance_meters) / float(deltaT)

            # Check if we have to notify the radio about AOS (Acquisition of Signal) / LOS (Loss of Signal)
            if (useRadio and args.send_aos_los):
                if elevation >= aos_elevation:
                    # See if we transitioned up:
                    if lastElevation < aos_elevation:
                        # We transitioned:
                        message="AOS\n"
                        netPortFreq.send(bytes(message.encode()))
                        data = netPortFreq.recv(BUFFER_SIZE)
                        result=data.decode('utf8')
                else:
                    # See if we transitioned down:
                    if lastElevation >= aos_elevation:
                        # We transitioned:
                        message="LOS\n"
                        netPortFreq.send(bytes(message.encode()))
                        data = netPortFreq.recv(BUFFER_SIZE)
                        result=data.decode('utf8')
                    
                lastElevation = elevation
                
            if len(args.rotor) > 0:
                # check our limits if we have any
                executeMove = True
                
                if usingRotorLimits:
                    if rotorLimitsReversed:
                        # if we're less than the left limit but not within the right limit, don't move
                        if azimuth < float(args.rotorleftlimit) and azimuth > float(args.rotorrightlimit):
                            executeMove = False
                    else:
                        # if we're not between our set limits, don't move
                        if azimuth < float(args.rotorleftlimit) or azimuth > float(args.rotorrightlimit):
                            executeMove = False
                        
                    if args.rotorelevationlimit != -1:
                        if elevation > float(args.rotorelevationlimit):
                            executeMove = False
                            
                    if executeMove:
                        retVal = RCmoveToPosition(args.rotor, int(args.rotortype),  int(args.rotorbaud),  azimuth,  elevation)
                    else:
                        print('[Info] Rotor would violate user-configured limits.  No move sent.')
                else:
                    if args.rotorelevationlimit != -1:
                        if elevation > float(args.rotorelevationlimit):
                            executeMove = False
                            
                    if executeMove:
                        retVal = RCmoveToPosition(args.rotor, int(args.rotortype),  int(args.rotorbaud),  azimuth,  elevation)
                    else:
                        print('[Info] Rotor would violate user-configured limits.  No move sent.')
                
            print("\nAziumuth:\t%.2f degrees" % azimuth)
            print("Elevation:\t%.2f degrees" % elevation)
            print("Distance:\t%.2f miles  / %.2f km" % (distance, (distance_meters/1000.0)))
            print("Percent illumination:\t%.2f%%" % (almanac.fraction_illuminated(planets,planetaryBody,t)*100.0))
            print("Relative Velocity:\t%.2f m/s [- is towards, + is away]" % (relativeVelocity,))
            if args.freq != 0:
                print("\nFrequency: %.2f Hz" % float(args.freq))
                dopplerFreq = doppler_shift(float(args.freq),relativeVelocity)
                dopplerShift = dopplerFreq - float(args.freq)
                print("Doppler Shift: %.2f Hz" % dopplerShift)
                print("Doppler Frequency: %.2f Hz" % dopplerFreq)

            local_tz = get_localzone()
            # Get now in local time
            timeCheck = datetime.now(local_tz)
            # Get hour zero and end of day in local time
            startTime = newtime=timeCheck - timedelta(hours=timeCheck.hour) - timedelta(minutes=timeCheck.minute) - timedelta(seconds=timeCheck.second)
            endTime = newtime=startTime + timedelta(hours=23) +  timedelta(minutes=59) + timedelta(seconds=59)
            # convert to UTC
            utcStart=startTime.astimezone(pytz.utc)
            utcEnd=endTime.astimezone(pytz.utc)
            # Build objects and get rise/set
            t0 = ts.utc(utcStart.year, utcStart.month, utcStart.day, utcStart.hour,  utcStart.minute,  utcStart.second)
            t1 = ts.utc(utcEnd.year, utcEnd.month, utcEnd.day, utcEnd.hour,  utcEnd.minute,  utcEnd.second)
            t, y = almanac.find_discrete(t0, t1, targetUpAt(observer,target))

            targetrise = None
            targetset = None
            
            if len(y) > 0:
                if y[0] == True:
                    targetrise = t[0]
                    if len(t) > 1:
                        targetset = t[1]
                    else:
                        targetset = None
                else:
                    if len(t) > 1:
                        targetrise = t[1]
                    else:
                        targetrise = None
                        
                    targetset = t[0]

            if targetrise is not None:
                print("\nTarget Rise in the next 24 hours: " + targetrise.astimezone(local_tz).strftime("%m/%d/%Y %H:%M:%S") + " [" + str(local_tz) + "]")
            else:
                print("\nTarget Rise in the next 24 hours: None")
                
            if targetset is not None:
                print("Target Set in the next 24 hours: " + targetset.astimezone(local_tz).strftime("%m/%d/%Y %H:%M:%S") + " [" + str(local_tz) + "]")
            else:
                print("\nTarget Set in the next 24 hours: None")

            print("")

            if useRadio:
                #message="F " + str(dopplerFreq) + "\n"
                message = radioCommand.replace("<frequency>", str(int(dopplerFreq)))
                if netPortFreq:
                    try:
                        netPortFreq.send(bytes(message.encode()))
                        data = netPortFreq.recv(BUFFER_SIZE)
                        result=data.decode('utf8')
                        
                        if len(result) > 0:
                            if (radioType == RADIOTYPE_GQRX):
                                if not ('RPRT 0' in result):
                                    print("ERROR setting frequency.  Radio returned error message:" + result)
                            else:
                                if (radioType == RADIOTYPE_SDRSHARP):
                                    if not ('{"Result":"OK"}' in result):
                                        if 'Not tunable' in result:
                                            print("ERROR: Does not look like the receiver is started.  Start SDRSharp receiving then tuning should work.")
                                        else:
                                            print("ERROR setting frequency.  Radio returned error message:" + result)
                    except Exception as e:
                        print("ERROR sending data to radio: " + str(e) + " (" + str(e.errno) + ")")
                        if e.errno == 32:
                            # Attempt to reconnect
                            netPortFreq.close()
                            netPortFreq = None
                            
                        if e.errno == 32 or e.errno == 9:
                            try:
                                print("Attempting to reconnect to radio...")
                                netPortFreq = None
                                netPortFreq = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                netPortFreq.connect((host, port))
                                print("Reconnected.")
                            except Exception as e:
                                print("ERROR: Unable to reconnect to radio at " + args.radio + ". Error: " + str(e))
                        else:
                            print("ERROR: Unable to talk to radio at " + args.radio + ". Error: " + str(e))
                    
            if useRadio or useRotor:
                print("Sleeping " + str(delay) + " seconds...")
                time.sleep(delay)
    except KeyboardInterrupt:
        pass

    if netPortFreq:
        try:
            netPortFreq.close()
            netPortFreq = None
        except:
            pass
        
    if netPortRotor:
        try:
            netPortRotor.close()
            netPortRotor = None
        except:
            pass
        
    if useRadio:
        s.close()

