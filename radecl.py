#!/usr/bin/python3

# See http://learn.astropy.org/rst-tutorials/Coordinates-Transform.html?highlight=filtertutorials
# For coordinate transform examples

import sys
from astropy.coordinates import SkyCoord
from astropy.coordinates import EarthLocation
from astropy.time import Time
from astropy import units as u
from astropy.coordinates import AltAz

import argparse
import socket
import time

# -------------------  Global Vars -------------------------------------
netPortRotor = None
lastElevation=-999.0

# -------------------  Global Functions ----------------------------------------
def socketConnect(server, port):
    global netPortRotor
    
    if not netPortRotor:
        netPortRotor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            netPortRotor.connect((server, port))
        except:
            print("ERROR: Unable to connect to " + server + ":" + str(port), file=sys.stderr)
            netPortRotor = None
            
def RCmoveToPosition(port, azimuth, elevation):
        # Port will be <ip>:<port>
        
        if azimuth < 0.0 or azimuth > 360.0:
            return -1 

        if elevation < 0:
            elevation = 0
            
        if elevation > 360:
            return -1 

        if ':' in port:
            if not netPortRotor:
                params = port.split(":")
                socketConnect(params[0], int(params[1]))
                
            if netPortRotor:
                cmdString = "P " + str(azimuth) + " " + str(elevation) + "\n"
                netPortRotor.send(cmdString.encode('utf-8'))
                
            return 0
        else:
            print("ERROR: Bad port specification.", file=sys.stderr)
            return -1

# -------------------  Main ----------------------------------------
if __name__ == '__main__':
    argparser = argparse.ArgumentParser(description='RA/DEC to Az/El Converter with Rotor Control (via rotctld)')
    argparser.add_argument('--ra', help="Target Right Ascention (can just be degrees '9.81625' or can be '<#>h<#>m<#s>')", default="", required=True)
    argparser.add_argument('--dec', help="Target Declination (can just be degrees '10.88806' or can be '<#>d<#>m<#s>'", default="", required=True)
    argparser.add_argument('--lat', help="Observer Latitude (decimal notation. Example: 40.1234)", default="", required=True)
    argparser.add_argument('--long', help="Observer Longitude (decimal notation)", default="", required=True)
    argparser.add_argument('--altitude', help="Observer Altitude (in meters)", default=-999.0, required=True)
    argparser.add_argument('--azcorrect', help="Degrees to adjust calculated azimuth.  For example, useful if accounting for magnetic vs. true north.", default=0, required=False)
    argparser.add_argument('--rotor', help="Rotctld-compatible network rotor controller.  Specify as <ip>:<port>", default="", required=False)
    argparser.add_argument('--delay', help="Time in seconds between updates (default is single shot)", default=0, required=False)
    argparser.add_argument('--rotorleftlimit', help="If needed, can provide a rotor 'left' limit in degrees. For instance if obstructions block rotation or view.  Default is no restriction.  Note: if either left/right limit is noted, both are required.", default=-1, required=False)
    argparser.add_argument('--rotorrightlimit', help="If needed, can provide a rotor 'right' limit in degrees. For instance if obstructions block rotation or view.  Default is no restriction. Note: if either left/right limit is noted, both are required.", default=-1, required=False)
    argparser.add_argument('--rotorelevationlimit', help="If needed, can provide a rotor 'elevation' limit in degrees. For instance if obstructions block rotation or view.  Default is 90 degrees (straight up).", default=-1, required=False)
    argparser.add_argument('--utcdate', help="[Alternate date] If provided, the UTC date and time will be used for the calculation rather than the current date/time.  Format: year/month/day hh:mm:ss", default="", required=False)

    # Parse Args
    args = argparser.parse_args()
    delay= int(args.delay)
    azcorrect = float(args.azcorrect)
    
    # Ground point of reference / where are we?
    earthLat = float(args.lat)*u.deg
    earthLong = float(args.long)*u.deg
    altitude=float(args.altitude)*u.m  # Make sure it has units of meter

    # What do we want to look at:
    # ra = 9.81625*u.deg
    #decl = 0.88806*u.deg
    
    # Since we may get a float or a string, first try to cast it to a float.  
    # If it throws an exception, just treat it as a string.
    try:
        ra = float(args.ra)*u.deg
    except:
        ra = args.ra
        
    try:
        decl = float(args.dec)*u.deg
    except:
        decl = args.dec
    
    # Set up rotor if specified
    if len(args.rotor) > 0:
        useRotor = True
    else:
        useRotor = False
    
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

    # Check if we have a UTC date
    if (len(args.utcdate) > 0):
        datestr = args.utcdate.strip('"')
        datestr = datestr.strip("'")
    else:
        datestr = ""

    # ---------------------  Now do the work ----------------------------------------------
    # Some predefined observing sites are available by name, can see list at:
    # EarthLocation.get_site_names()
    # and use EarthLocation.of_site('<name from list>')

    # Set up Earth observing Location
    groundLoc = EarthLocation(lat=earthLat, lon=earthLong, height=altitude)

    # Set up our target
    raDeclTarget = SkyCoord(ra, decl, frame='icrs')

    loop = True # First time through we want to execute
    
    try:
        # If we specified a delay and we did not specify a fixed UTC time, loop.
        while (loop):
            # Calculate Az / El
            # For transforms, need to incorporate when
            if (len(datestr) == 0):
                observingTime = Time.now()
            else:
                # Can also get time from time string: Time.strptime('2019-06-25 15:00:00', '%Y-%m-%d %H:%M:%S')
                # NOTE: time string is UTC
                observingTime = Time.strptime(datestr)
                
            altAzCoord = None  # Release any previous memory if looping
            altAzCoord = AltAz(location=groundLoc,  obstime=observingTime)
            print("Calculating...", file=sys.stderr)
            altAz=raDeclTarget.transform_to(altAzCoord)

            azimuth = altAz.az.degree
            elevation = altAz.alt.degree
            if (azcorrect != 0.0):
                azimuth = azimuth + azcorrect
                
            print('UTC Time: ' + str(observingTime))
            if (azcorrect == 0.0):
                print('Azimuth: ' + '%.4f' % azimuth + ' degrees')
            else:
                print('Azimuth (Calculated): ' + '%.4f' % azimuth + ' degrees')
                print('Azimuth (Corrected): ' + '%.4f' % azimuth + ' degrees')
                
            print('Elevation: ' + '%.4f' % elevation + ' degrees')
            
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
                        retVal = RCmoveToPosition(args.rotor,  azimuth,  elevation)
                    else:
                        print('[Info] Rotor would violate user-configured limits.  No move sent.')
                else:
                    if args.rotorelevationlimit != -1:
                        if elevation > float(args.rotorelevationlimit):
                            executeMove = False
                            
                    if executeMove:
                        retVal = RCmoveToPosition(args.rotor, azimuth,  elevation)
                    else:
                        print('[Info] Rotor would violate user-configured limits.  No move sent.')

            # Determine if we should loop and if so, delay
            if (delay > 0 and len(datestr)==0):
                loop = True
                time.sleep(delay)
            else:
                loop = False
            
    except KeyboardInterrupt:
        pass
