import argparse
import requests
import pandas as pd
import numpy as np
import os
from math import atan, atan2, sqrt, pi
import time
import json
from io import StringIO


# ── Weather-adjustment constants and helpers ──────────────────────────────────

STANDARD_RHO = 1.195  # kg/m³ at sea level, ~70°F (matches process_data.py)

# MLB's live feed omits venue.location.elevation for most international
# parks, so without an override Mexico City games look like sea level and
# IVB/HB go un-adjusted despite ~7,350 ft of thin air.
VENUE_ELEVATION_FT_OVERRIDE = {
    5340: 7349,  # Estadio Alfredo Harp Helú, Mexico City
    2493: 1765,  # Estadio de Béisbol Monterrey, Monterrey
    5150: 125,   # Gocheok Sky Dome, Seoul
    5160: 144,   # Tokyo Dome, Tokyo
    4895: 16,    # London Stadium, London
}


def compute_air_density(elevation_ft, temp_f):
    """Air density (kg/m³) from elevation and temperature using barometric formula."""
    elevation_m = elevation_ft * 0.3048
    P = 101325 * (1 - 2.2558e-5 * elevation_m) ** 5.2556
    T = (temp_f - 32) * 5 / 9 + 273.15
    return P / (287.05 * T)


def compute_weather_adj_factor(rho_game):
    """Density-only adjustment factor for pitch movement.

    xIndVrtBrk = rawIVB × factor,  xHorzBrk = rawHB × factor.

    Uses ρ^(2/3) scaling: thinner air reduces Magnus force but also reduces
    drag → longer flight time → partial compensation.  Net deflection ∝ ρ^(2/3).

    Returns 1.0 when inputs are missing or invalid.
    """
    if not rho_game or rho_game <= 0:
        return 1.0

    return (STANDARD_RHO / rho_game) ** (2 / 3)


class BaseballSavantFocusedDownloader:
    def __init__(self, download_dir="/Users/wallyhuron/Downloads"):
        """
        Initialize the Baseball Savant downloader with a focus on individual game data
        """
        self.download_dir = download_dir
        self.session = requests.Session()

        # Set headers to mimic browser request - important for not getting blocked
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://baseballsavant.mlb.com/gamefeed'
        })

        # Create download directory if it doesn't exist
        os.makedirs(download_dir, exist_ok=True)

        # Initialize team mappings
        self._initialize_team_mappings()

    def _initialize_team_mappings(self):
        """Initialize dictionaries for team name/abbreviation/ID mappings"""
        # Team name to abbreviation mapping
        self.team_name_to_abbrev = {
            "Arizona Diamondbacks": "ARI",
            "Athletics": "ATH",
            "Atlanta Braves": "ATL",
            "Baltimore Orioles": "BAL",
            "Boston Red Sox": "BOS",
            "Chicago Cubs": "CHC",
            "Chicago White Sox": "CWS",
            "Cincinnati Reds": "CIN",
            "Cleveland Guardians": "CLE",
            "Colorado Rockies": "COL",
            "Detroit Tigers": "DET",
            "Houston Astros": "HOU",
            "Kansas City Royals": "KCR",
            "Los Angeles Angels": "LAA",
            "Los Angeles Dodgers": "LAD",
            "Miami Marlins": "MIA",
            "Milwaukee Brewers": "MIL",
            "Minnesota Twins": "MIN",
            "New York Mets": "NYM",
            "New York Yankees": "NYY",
            "Philadelphia Phillies": "PHI",
            "Pittsburgh Pirates": "PIT",
            "San Diego Padres": "SDP",
            "San Francisco Giants": "SFG",
            "Seattle Mariners": "SEA",
            "St. Louis Cardinals": "STL",
            "Tampa Bay Rays": "TBR",
            "Texas Rangers": "TEX",
            "Toronto Blue Jays": "TOR",
            "Washington Nationals": "WSH",
        }

        # Statcast Search abbreviations that differ from ours (all others pass through)
        self.team_abbrev_to_statcast = {
            "ATH": "OAK",
            "KCR": "KC",
            "SDP": "SD",
            "SFG": "SF",
            "TBR": "TB",
        }

        # Team abbreviation to team ID mapping for MLB Stats API
        self.team_abbrev_to_id = {
            "ARI": 109,  # Arizona Diamondbacks
            "ATH": 133,  # Athletics
            "ATL": 144,  # Atlanta Braves
            "BAL": 110,  # Baltimore Orioles
            "BOS": 111,  # Boston Red Sox
            "CHC": 112,  # Chicago Cubs
            "CWS": 145,  # Chicago White Sox
            "CIN": 113,  # Cincinnati Reds
            "CLE": 114,  # Cleveland Guardians
            "COL": 115,  # Colorado Rockies
            "DET": 116,  # Detroit Tigers
            "HOU": 117,  # Houston Astros
            "KCR": 118,  # Kansas City Royals
            "LAA": 108,  # Los Angeles Angels
            "LAD": 119,  # Los Angeles Dodgers
            "MIA": 146,  # Miami Marlins
            "MIL": 158,  # Milwaukee Brewers
            "MIN": 142,  # Minnesota Twins
            "NYM": 121,  # New York Mets
            "NYY": 147,  # New York Yankees
            "PHI": 143,  # Philadelphia Phillies
            "PIT": 134,  # Pittsburgh Pirates
            "SDP": 135,  # San Diego Padres
            "SFG": 137,  # San Francisco Giants
            "SEA": 136,  # Seattle Mariners
            "STL": 138,  # St. Louis Cardinals
            "TBR": 139,  # Tampa Bay Rays
            "TEX": 140,  # Texas Rangers
            "TOR": 141,  # Toronto Blue Jays
            "WSH": 120,  # Washington Nationals
        }

    def get_player_name(self, player_id, player_full_name, game_data):
        """
        Get a player name in 'Last, First' format using the API's own
        firstName/lastName fields from gameData.players.

        Works for both pitchers and batters.

        The API already knows the correct split for multi-word last names
        (e.g., Woods Richardson), suffixes (Jr., III), and prefixes (De La Cruz).

        Falls back to fullName string parsing only if the player data is missing.
        """
        # Look up the player in gameData.players (keyed as "ID{player_id}")
        player_key = f"ID{player_id}"
        player_info = game_data.get('players', {}).get(player_key, {})

        # Best option: the API provides lastFirstName already formatted
        last_first = player_info.get('lastFirstName', '')
        if last_first:
            return last_first

        # Second option: build it from separate firstName and lastName fields
        first_name = player_info.get('firstName', '')
        last_name = player_info.get('lastName', '')
        if first_name and last_name:
            return f"{last_name}, {first_name}"

        # Fallback: parse the fullName string (least reliable)
        return self._parse_player_name(player_full_name)

    def _parse_player_name(self, full_name):
        """
        Fallback parser for player names when API player data is unavailable.
        Handles suffixes and common multi-word last name prefixes.
        """
        if not full_name or ' ' not in full_name:
            return full_name

        # Suffixes to strip and reattach to the last name
        suffixes = {'jr.', 'jr', 'sr.', 'sr', 'ii', 'iii', 'iv', 'v'}

        parts = full_name.split()

        # Check for a trailing suffix
        suffix = ''
        if len(parts) > 2 and parts[-1].lower().rstrip('.') in {s.rstrip('.') for s in suffixes}:
            suffix = ' ' + parts.pop()

        # Common last-name prefixes (case-insensitive check)
        last_name_prefixes = {
            'de', 'la', 'da', 'del', 'della', 'di', 'du', 'dos', 'das',
            'van', 'von', 'le', 'el', 'al', 'st.', 'san', 'santa',
            'los', 'las', 'des', "o'",
        }

        if len(parts) <= 2:
            # Simple "First Last" case
            first_name = parts[0]
            last_name = parts[1] + suffix
            return f"{last_name}, {first_name}"

        # For 3+ parts, scan from the second token forward to find where
        # the last name begins. A token that is a known prefix or is followed
        # only by one more token (the final surname word) starts the last name.
        # We assume the first token is always part of the first name.
        last_name_start = None
        for i in range(1, len(parts)):
            if parts[i].lower().rstrip('.') in last_name_prefixes:
                last_name_start = i
                break

        # If no prefix found, assume everything except the first token is the last name.
        # This handles cases like "Simeon Woods Richardson" where "Woods Richardson"
        # is the last name but has no standard prefix.
        if last_name_start is None:
            last_name_start = 1

        first_name = ' '.join(parts[:last_name_start])
        last_name = ' '.join(parts[last_name_start:]) + suffix

        # Safety check: don't produce an empty first or last name
        if not first_name or not last_name:
            return full_name

        return f"{last_name}, {first_name}"

    def get_team_abbreviation(self, team_name):
        """
        Get the team abbreviation from the full team name
        """
        return self.team_name_to_abbrev.get(team_name, team_name)

    def get_team_id(self, team_abbrev):
        """
        Get the MLB team ID from the team abbreviation
        """
        return self.team_abbrev_to_id.get(team_abbrev.upper())

    def get_statcast_team_abbrev(self, team_abbrev):
        """
        Convert internal team abbreviation to Statcast Search abbreviation
        """
        return self.team_abbrev_to_statcast.get(team_abbrev.upper(), team_abbrev.upper())

    def is_barrel(self, exit_velo, launch_angle):
        """
        Estimate whether a batted ball is a barrel using the Statcast formula.

        A barrel (launch_speed_angle = 6) requires:
        - launch_angle in [8, 50]
        - exit_velo >= 98
        - exit_velo * 1.5 - launch_angle >= 117
        - exit_velo + launch_angle >= 124

        Returns: True if barrel, False otherwise
        """
        if exit_velo is None or launch_angle is None:
            return False

        try:
            ev = float(exit_velo)
            la = float(launch_angle)
        except (ValueError, TypeError):
            return False

        return (la >= 8 and la <= 50 and ev >= 98 and ev * 1.5 - la >= 117 and ev + la >= 124)

    def spin_axis_to_tilt(self, spin_axis):
        """
        Convert spin axis (degrees) to tilt (clock format as string).

        From Driveline:
        - 180 degrees = 12:00 (pure backspin)
        - Each hour = 30 degrees
        - Each minute = 0.5 degrees

        Examples:
        - 180 -> 12:00 (pure backspin, 4-seam fastball)
        - 215 -> 1:10 (typical RHP fastball)
        - 0 or 360 -> 6:00 (pure topspin, 12-6 curveball)
        - 270 -> 3:00 (pure sidespin)
        - 90 -> 9:00 (gyro spin)

        Returns: Tilt as string (e.g., "1:10") or None if data is missing
        """
        if spin_axis is None:
            return None

        # Convert spin axis to decimal clock hours
        # 180 degrees = 12:00, so divide by 30 and subtract 6
        decimal_hours = spin_axis / 30 - 6

        # Handle wrap-around for clock (0-12 range)
        if decimal_hours < 0:
            decimal_hours += 12
        elif decimal_hours >= 12:
            decimal_hours -= 12

        # Extract hours and minutes
        hours = int(decimal_hours)
        minutes = int((decimal_hours - hours) * 60)

        # Handle 0 -> 12 for display
        if hours == 0:
            hours = 12

        return f"{hours}:{minutes:02d}"

    def calculate_break_tilt(self, ivb, hb):
        """
        Calculate break tilt from IndVertBrk and HorzBrk.

        Break tilt is the direction of the actual pitch movement vector,
        as opposed to release tilt which is the spin axis direction.
        The difference between the two reveals seam-shifted wake (SSW).

        Uses atan2(HorzBrk, IndVertBrk) to get the angle of the movement
        vector measured clockwise from 12:00 (from the pitcher's perspective).

        In MLB API / Trackman data, positive HorzBrk = arm-side movement,
        which maps to clockwise rotation on the tilt clock.

        Returns: Break tilt as clock string (e.g., "1:30") or None if data is missing
        """
        if ivb is None or hb is None:
            return None

        try:
            ivb = float(ivb)
            hb = float(hb)
        except (ValueError, TypeError):
            return None

        # Handle zero movement edge case
        if ivb == 0 and hb == 0:
            return None

        # atan2(HorzBrk, IndVertBrk) gives angle from 12:00 (pure rise),
        # with positive values going clockwise (arm-side)
        angle_rad = atan2(hb, ivb)
        angle_deg = angle_rad * (180 / pi)

        # Normalize to 0-360
        if angle_deg < 0:
            angle_deg += 360

        # Convert degrees to clock notation
        # 360 degrees = 12 hours = 720 minutes
        total_minutes = angle_deg / 360 * 720
        hours = int(total_minutes // 60) % 12
        minutes = int(total_minutes % 60)

        if hours == 0:
            hours = 12

        return f"{hours}:{minutes:02d}"

    def calculate_approach_angles(self, vy0, vz0, vx0, ay, az, ax):
        """
        Calculate VAA (Vertical Approach Angle) and HAA (Horizontal Approach Angle).

        Formulas from Fangraphs:
        https://blogs.fangraphs.com/a-visualized-primer-on-vertical-approach-angle-vaa/

        vy_f = -sqrt(vy0^2 - (2 * ay * (y0 - yf)))
        t = (vy_f - vy0) / ay
        vz_f = vz0 + (az * t)
        VAA = -arctan(vz_f/vy_f) * (180 / pi)

        vx_f = vx0 + (ax * t)
        HAA = -arctan(vx_f/vy_f) * (180 / pi)

        Where:
        - y0 = 50 (release point at y=50 feet)
        - yf = 17/12 (front of home plate, 17 inches in feet)

        Returns: (VAA, HAA) or (None, None) if data is missing
        """
        if any(v is None for v in [vy0, vz0, vx0, ay, az, ax]):
            return None, None

        y0 = 50
        yf = 17 / 12

        try:
            discriminant = vy0 ** 2 - (2 * ay * (y0 - yf))
            if discriminant < 0:
                return None, None
            vy_f = -sqrt(discriminant)
            t = (vy_f - vy0) / ay
            vz_f = vz0 + (az * t)
            vx_f = vx0 + (ax * t)

            VAA = -atan(vz_f / vy_f) * (180 / pi)
            HAA = -atan(vx_f / vy_f) * (180 / pi)
            return VAA, HAA

        except (ValueError, ZeroDivisionError):
            return None, None

    def simplify_description(self, description):
        """
        Simplify pitch descriptions into human-readable labels.

        Grouped:
        - In Play: covers all hit-into-play variants
        - Swinging Strike: includes swinging strike blocked and foul tips
        - Ball: includes blocked balls

        Standalone (kept granular for analysis):
        - Called Strike, Hit By Pitch, Foul, Foul Bunt, Bunt Foul Tip,
          Missed Bunt, Intent Ball, Pitchout, Swinging Pitchout, Foul Pitchout

        Returns simplified description or original if no mapping found
        """
        if not description:
            return description

        # Map from live API human-readable descriptions to simplified labels
        DESCRIPTION_MAP = {
            # Grouped: In Play
            'in play, out(s)': 'In Play',
            'in play, no out': 'In Play',
            'in play, run(s)': 'In Play',
            # Grouped: Swinging Strike
            'swinging strike': 'Swinging Strike',
            'swinging strike (blocked)': 'Swinging Strike',
            'foul tip': 'Swinging Strike',
            # Grouped: Ball
            'ball': 'Ball',
            'ball in dirt': 'Ball',
            # Standalone
            'called strike': 'Called Strike',
            'hit by pitch': 'Hit By Pitch',
            'foul': 'Foul',
            'foul bunt': 'Foul Bunt',
            'bunt foul tip': 'Bunt Foul Tip',
            'missed bunt': 'Missed Bunt',
            'intent ball': 'Intent Ball',
            'pitchout': 'Pitchout',
            'swinging pitchout': 'Swinging Pitchout',
            'foul pitchout': 'Foul Pitchout',
        }

        return DESCRIPTION_MAP.get(description.lower(), description)


    def get_team_games(self, team_abbrev, start_date, end_date):
        """
        Get all games for a specific team within a date range
        """
        print(f"Finding games for {team_abbrev} from {start_date} to {end_date}...")

        # Convert team abbreviation to team ID
        team_id = self.get_team_id(team_abbrev)
        if not team_id:
            print(f"Error: Invalid team abbreviation '{team_abbrev}'")
            return []

        # MLB Stats API endpoint for schedule
        url = "https://statsapi.mlb.com/api/v1/schedule"

        params = {
            "teamId": team_id,
            "startDate": start_date,
            "endDate": end_date,
            "sportId": 1,  # MLB
            "gameType": "E,S,R,F,D,L,W"  # Spring Training and Regular Season
        }

        try:
            response = self.session.get(url, params=params, timeout=30)

            if response.status_code != 200:
                print(f"Error: Received status code {response.status_code}")
                return []

            data = response.json()

            # Extract game PKs
            game_pks = []

            if "dates" in data:
                for date_data in data["dates"]:
                    if "games" in date_data:
                        for game in date_data["games"]:
                            game_pks.append(game["gamePk"])

            print(f"Found {len(game_pks)} games for {team_abbrev} in the specified date range.")
            return game_pks

        except Exception as e:
            print(f"Error getting team games: {str(e)}")
            return []

    def download_game_data(self, game_pk, filter_team=None):
        """
        Download pitch-by-pitch data using the MLB Stats API
        Returns the DataFrame directly rather than saving to a file
        """
        print(f"Downloading data for game {game_pk}...")

        # Using the MLB Stats API endpoint
        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

        try:
            response = self.session.get(url, timeout=60)

            if response.status_code != 200:
                print(f"Error: Received status code {response.status_code}")
                print(f"Response: {response.text[:500]}")
                return None

            # Parse the JSON response
            try:
                data = response.json()
            except json.JSONDecodeError:
                print("Error: Failed to parse JSON response")
                print(f"Response: {response.text[:500]}")
                return None

            # Check if we received valid data
            if not data or 'liveData' not in data or 'plays' not in data['liveData']:
                print("Error: No play data in response")
                print(f"Response keys: {list(data.keys()) if data else 'None'}")
                return None

            # Get game information
            game_data = data.get('gameData', {})
            game_date = game_data.get('datetime', {}).get('officialDate', '')
            # Get team information and convert to abbreviations
            teams = game_data.get('teams', {})
            home_team_name = teams.get('home', {}).get('name', 'Unknown')
            away_team_name = teams.get('away', {}).get('name', 'Unknown')
            home_team = self.get_team_abbreviation(home_team_name)
            away_team = self.get_team_abbreviation(away_team_name)

            # ── Weather & venue data for movement adjustment ──
            weather = game_data.get('weather', {})
            venue = game_data.get('venue', {})
            venue_location = venue.get('location', {})
            venue_field_info = venue.get('fieldInfo', {})

            game_temp = None
            game_elevation = None
            game_rho = None

            try:
                temp_str = weather.get('temp')
                elev_val = venue_location.get('elevation')
                if elev_val is None:
                    elev_val = VENUE_ELEVATION_FT_OVERRIDE.get(venue.get('id'))

                if temp_str is not None:
                    game_temp = float(temp_str)
                if elev_val is not None:
                    game_elevation = float(elev_val)

                # Air density
                if game_temp is not None and game_elevation is not None:
                    game_rho = compute_air_density(game_elevation, game_temp)
            except (ValueError, TypeError):
                pass  # any parse failure → defaults (no adjustment)

            # Extract all plays
            all_plays = data['liveData']['plays'].get('allPlays', [])

            # Get boxscore teams for pitcher team detection
            boxscore_teams = data.get('liveData', {}).get('boxscore', {}).get('teams', {})
            home_players = boxscore_teams.get('home', {}).get('players', {})
            away_players = boxscore_teams.get('away', {}).get('players', {})

            # Extract pitch-by-pitch data
            pitches = []
            for play in all_plays:
                # Get batter stance
                bats = play.get('matchup', {}).get('batSide', {}).get('code', '')

                # Get pitcher information
                pitcher_id = play.get('matchup', {}).get('pitcher', {}).get('id', 0)
                pitcher_full_name = play.get('matchup', {}).get('pitcher', {}).get('fullName', '')

                # Use API player data for correct name formatting
                pitcher_name = self.get_player_name(pitcher_id, pitcher_full_name, game_data)

                # Get batter information
                batter_id = play.get('matchup', {}).get('batter', {}).get('id', 0)
                batter_full_name = play.get('matchup', {}).get('batter', {}).get('fullName', '')
                batter_name = self.get_player_name(batter_id, batter_full_name, game_data)

                # Determine which team the pitcher belongs to
                pitcher_team = None

                # Check if pitcher is on home team
                for player_info in home_players.values():
                    if player_info.get('person', {}).get('id') == pitcher_id:
                        pitcher_team = home_team
                        break

                # If not found, check away team
                if pitcher_team is None:
                    for player_info in away_players.values():
                        if player_info.get('person', {}).get('id') == pitcher_id:
                            pitcher_team = away_team
                            break

                # Determine which team the batter belongs to
                b_team = None

                for player_info in home_players.values():
                    if player_info.get('person', {}).get('id') == batter_id:
                        b_team = home_team
                        break

                if b_team is None:
                    for player_info in away_players.values():
                        if player_info.get('person', {}).get('id') == batter_id:
                            b_team = away_team
                            break

                # If filtering by team and this pitcher is not from that team, skip this play
                if filter_team and pitcher_team != filter_team:
                    continue

                # Get pitch hand from the matchup data
                p_throws = play.get('matchup', {}).get('pitchHand', {}).get('code', '')

                # Fall back to player data only if matchup data is missing
                if not p_throws:
                    player_key = f"ID{pitcher_id}"
                    player_info = game_data.get('players', {}).get(player_key, {})
                    p_throws = player_info.get('pitchHand', {}).get('code', 'R')

                # Get the PA result event (single, home_run, strikeout, etc.)
                pa_event = play.get('result', {}).get('event', '')

                # Get the at-bat number (1-indexed to match Statcast Search)
                at_bat_number = play.get('atBatIndex', 0) + 1

                # Process each pitch in the at-bat
                # Track the count before each pitch
                play_events = play.get('playEvents', [])
                pre_pitch_balls = 0
                pre_pitch_strikes = 0

                # Pre-compute which pitch index is the last actual pitch in this PA
                last_pitch_idx = None
                for i in range(len(play_events) - 1, -1, -1):
                    if play_events[i].get('isPitch', False):
                        last_pitch_idx = i
                        break

                for pitch_idx, pitch in enumerate(play_events):
                    if pitch.get('isPitch', False):
                        # Get velocity and acceleration data for angle calculations
                        coords = pitch.get('pitchData', {}).get('coordinates', {})
                        vx0 = coords.get('vX0')
                        vy0 = coords.get('vY0')
                        vz0 = coords.get('vZ0')
                        ax = coords.get('aX')
                        ay = coords.get('aY')
                        az = coords.get('aZ')
                        release_pos_y = coords.get('y0')

                        # Get break values for break tilt calculation
                        ivb = pitch.get('pitchData', {}).get('breaks', {}).get('breakVerticalInduced')
                        hb = pitch.get('pitchData', {}).get('breaks', {}).get('breakHorizontal')

                        # Calculate release tilt from spin axis
                        spin_direction = pitch.get('pitchData', {}).get('breaks', {}).get('spinDirection')
                        release_tilt = self.spin_axis_to_tilt(spin_direction)

                        # Calculate observed tilt from movement vector (IVB/HB)
                        observed_tilt = self.calculate_break_tilt(ivb, hb)

                        # Calculate approach angles (at plate)
                        VAA, HAA = self.calculate_approach_angles(vy0, vz0, vx0, ay, az, ax)

                        # Plate time (flight time from release to plate)
                        plate_time_raw = pitch.get('pitchData', {}).get('plateTime')
                        plate_time = round(plate_time_raw, 3) if plate_time_raw is not None else None

                        # Count BEFORE this pitch is thrown
                        count_str = f"{pre_pitch_balls}-{pre_pitch_strikes}"

                        # Get raw pitch type code and remap KC -> CU, FO -> FS
                        raw_pitch_type = pitch.get('details', {}).get('type', {}).get('code', '')
                        pitch_type_remap = {'KC': 'CU', 'FO': 'FS'}
                        pitch_type = pitch_type_remap.get(raw_pitch_type, raw_pitch_type)

                        # Extension from the live API (pitchData.extension)
                        extension_raw = pitch.get('pitchData', {}).get('extension')
                        extension = round(extension_raw, 2) if extension_raw is not None else None

                        # Strike zone boundaries
                        sz_top = pitch.get('pitchData', {}).get('strikeZoneTop')
                        sz_bot = pitch.get('pitchData', {}).get('strikeZoneBottom')
                        plate_z = pitch.get('pitchData', {}).get('coordinates', {}).get('pZ')
                        plate_x = pitch.get('pitchData', {}).get('coordinates', {}).get('pX')

                        # Determine if this is the final pitch of the PA
                        is_final_pitch = (pitch_idx == last_pitch_idx)

                        # Get hit data (only present on batted balls)
                        hit_data = pitch.get('hitData', {}) if 'hitData' in pitch else {}

                        # Estimate barrel from exit velo / launch angle (6 = barrel on 1-6 scale)
                        ev_raw = hit_data.get('launchSpeed')
                        la_raw = hit_data.get('launchAngle')
                        estimated_barrel = 6 if self.is_barrel(ev_raw, la_raw) else None

                        # Compute weather-adjusted IVB and HB
                        pitch_velo = pitch.get('pitchData', {}).get('startSpeed')
                        adj_ivb = None
                        adj_hb = None
                        try:
                            adj_factor = compute_weather_adj_factor(game_rho)
                            if ivb is not None:
                                adj_ivb = round(ivb * adj_factor, 1)
                            if hb is not None:
                                adj_hb = round(hb * adj_factor, 1)
                        except (ValueError, TypeError):
                            adj_ivb = ivb  # fall back to raw
                            adj_hb = hb

                        # Extract pitch data
                        pitch_data = {
                            'Game Date': game_date,
                            'PTeam': pitcher_team,
                            'Pitcher': pitcher_name,
                            'Throws': p_throws,
                            'Pitch Type': pitch_type,
                            'Velocity': pitch_velo,
                            'Spin Rate': pitch.get('pitchData', {}).get('breaks', {}).get('spinRate'),
                            'RTilt': release_tilt,
                            'OTilt': observed_tilt,
                            'IndVertBrk': ivb,
                            'HorzBrk': hb,
                            'xIndVrtBrk': adj_ivb,
                            'xHorzBrk': adj_hb,
                            'RelPosZ': pitch.get('pitchData', {}).get('coordinates', {}).get('z0'),
                            'RelPosX': pitch.get('pitchData', {}).get('coordinates', {}).get('x0'),
                            'Extension': extension,
                            'ArmAngle': None,  # filled by Statcast supplement
                            'EffectiveVelo': None,  # filled by Statcast supplement
                            'PlateZ': plate_z,
                            'PlateX': plate_x,
                            'SzTop': sz_top,
                            'SzBot': sz_bot,
                            'VAA': VAA,
                            'HAA': HAA,
                            'PlateTime': plate_time,
                            'BTeam': b_team,
                            'Batter': batter_name,
                            'Bats': bats,
                            'Count': count_str,
                            'Runners': None,  # filled by Statcast supplement (on_1b/on_2b/on_3b)
                            'Outs': play.get('about', {}).get('outs'),
                            'Description': self.simplify_description(pitch.get('details', {}).get('description', '')),
                            'Event': pa_event if is_final_pitch else '',
                            'ExitVelo': hit_data.get('launchSpeed'),
                            'LaunchAngle': hit_data.get('launchAngle'),
                            'Distance': hit_data.get('totalDistance'),
                            'BBType': 'bunt' if (hit_data.get('trajectory') or '').startswith('bunt_') else hit_data.get('trajectory'),
                            'HC_X': hit_data.get('coordinates', {}).get('coordX') if hit_data.get('coordinates') else None,
                            'HC_Y': hit_data.get('coordinates', {}).get('coordY') if hit_data.get('coordinates') else None,
                            'xBA': None,    # filled by Statcast supplement (estimated_ba_using_speedangle)
                            'xSLG': None,   # filled by Statcast supplement (estimated_slg_using_speedangle)
                            'xwOBA': None,  # filled by Statcast supplement (estimated_woba_using_speedangle)
                            'wOBAval': None,  # filled by Statcast supplement (woba_value)
                            'wOBAdom': None,  # filled by Statcast supplement (woba_denom)
                            'RunExp': None,  # filled by Statcast supplement (delta_pitcher_run_exp)
                            'Barrel': estimated_barrel,  # estimate from code_barrel formula; overwritten by Statcast launch_speed_angle if available
                            # Merge keys for Statcast Search supplement (dropped before final CSV)
                            '_game_pk': game_pk,
                            '_at_bat_number': at_bat_number,
                            '_pitch_number': pitch.get('pitchNumber'),
                            # Stable pitch identifier: game_pk + zero-padded at-bat + zero-padded pitch
                            'PitchID': f"{game_pk}_{at_bat_number:03d}_{(pitch.get('pitchNumber') or 0):02d}",
                        }

                        pitches.append(pitch_data)

                        # Update count for next pitch based on this pitch's result
                        # Get the count AFTER this pitch from the API
                        post_count = pitch.get('count', {})
                        pre_pitch_balls = post_count.get('balls', pre_pitch_balls)
                        pre_pitch_strikes = post_count.get('strikes', pre_pitch_strikes)
                        # Cap strikes at 2 for foul balls with 2 strikes
                        if pre_pitch_strikes > 2:
                            pre_pitch_strikes = 2

            # Create DataFrame from pitch data
            if not pitches:
                print("No pitch data found for this game")
                return None

            df = pd.DataFrame(pitches)

            # Format numeric columns with appropriate decimal places
            # Use pd.to_numeric to handle any non-numeric values (empty strings, etc.)
            # that can appear in early Spring Training games or incomplete data
            numeric_round_1 = ['Velocity', 'IndVertBrk', 'HorzBrk', 'xIndVrtBrk', 'xHorzBrk',
                               'ExitVelo', 'BatSpeed', 'SwingLength',
                               'AttackAngle', 'AttackDirection', 'SwingPathTilt',
                               'ArmAngle', 'EffectiveVelo']
            numeric_round_2 = ['VAA', 'HAA', 'HC_X', 'HC_Y',
                               'RelPosZ', 'RelPosX', 'Extension']
            numeric_round_3 = ['PlateZ', 'PlateX', 'SzTop', 'SzBot',
                               'RunExp', 'xBA', 'xSLG', 'xwOBA', 'wOBAval', 'wOBAdom']
            numeric_int = ['LaunchAngle', 'Distance']

            for col in numeric_round_1:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').apply(lambda x: f"{x:.1f}" if pd.notna(x) else '')
            for col in numeric_round_2:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').apply(lambda x: f"{x:.2f}" if pd.notna(x) else '')
            for col in numeric_round_3:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').apply(lambda x: f"{x:.3f}" if pd.notna(x) else '')
            for col in numeric_int:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')

            # Spin Rate: round to 0 decimals, then Int64
            if 'Spin Rate' in df.columns:
                df['Spin Rate'] = pd.to_numeric(df['Spin Rate'], errors='coerce').round(0).astype('Int64')

            print(f"Successfully processed {len(df)} pitches from game {game_pk}")
            return df

        except Exception as e:
            print(f"Error downloading game data: {str(e)}")
            return None

    def download_statcast_supplement(self, team_abbrev, start_date, end_date):
        """
        Download supplemental data from Statcast Search CSV endpoint.
        Provides columns not available in the live feed API:
        - arm_angle (ArmAngle)
        - bat_speed (BatSpeed)
        - swing_length (SwingLength)
        - attack_angle (AttackAngle)
        - attack_direction (AttackDirection)
        - swing_path_tilt (SwingPathTilt)
        - delta_pitcher_run_exp (RunExp)
        - on_1b, on_2b, on_3b (Runners)

        Returns a DataFrame keyed on game_pk, at_bat_number, pitch_number
        for merging with live feed data, or None if the request fails.
        """
        statcast_team = self.get_statcast_team_abbrev(team_abbrev)
        print(f"Downloading Statcast Search supplement for {team_abbrev} ({statcast_team})...")

        url = "https://baseballsavant.mlb.com/statcast_search/csv"

        params = {
            'all': 'true',
            'type': 'details',
            'game_date_gt': start_date,
            'game_date_lt': end_date,
            'team': statcast_team,
            'player_type': 'pitcher',
            'min_pitches': '0',
            'min_results': '0',
            'sort_col': 'pitches',
            'sort_order': 'desc',
        }

        try:
            response = self.session.get(url, params=params, timeout=60)

            if response.status_code != 200:
                print(f"Statcast Search returned status {response.status_code}")
                return None

            csv_text = response.text

            if not csv_text or csv_text.strip() == '' or 'No Results' in csv_text[:100]:
                print("Statcast Search returned no data (data may not be processed yet)")
                return None

            df = pd.read_csv(StringIO(csv_text))

            if df.empty:
                print("Statcast Search returned empty DataFrame")
                return None

            # Columns we need for merging
            merge_cols = ['game_pk', 'at_bat_number', 'pitch_number']
            supplement_cols = [
                'arm_angle',
                'effective_speed',
                'release_pos_y',
                'bat_speed',
                'swing_length',
                'attack_angle',
                'attack_direction',
                'swing_path_tilt',
                'delta_pitcher_run_exp',
                'estimated_ba_using_speedangle',
                'estimated_slg_using_speedangle',
                'estimated_woba_using_speedangle',
                'woba_value',
                'woba_denom',
                'on_1b',
                'on_2b',
                'on_3b',
                'launch_speed_angle',
            ]

            available_supplement = [c for c in supplement_cols if c in df.columns]
            missing_supplement = [c for c in supplement_cols if c not in df.columns]

            if missing_supplement:
                print(f"Warning: Statcast Search missing columns: {missing_supplement}")

            if not available_supplement:
                print("No supplement columns found in Statcast Search response")
                return None

            for col in merge_cols:
                if col not in df.columns:
                    print(f"Error: Merge key column '{col}' not found in Statcast Search data")
                    return None

            keep_cols = merge_cols + available_supplement
            df = df[keep_cols].copy()

            print(f"Statcast Search returned {len(df)} pitches with columns: {available_supplement}")
            return df

        except requests.exceptions.Timeout:
            print("Statcast Search request timed out (server may be slow)")
            return None
        except Exception as e:
            print(f"Error downloading Statcast Search data: {str(e)}")
            return None

    def merge_statcast_supplement(self, live_df, supplement_df):
        """
        Merge Statcast Search supplement data into the live feed DataFrame.
        """
        # Column name mapping from Statcast CSV names to our display names
        rename_map = {
            'arm_angle': 'ArmAngle',
            'effective_speed': 'EffectiveVelo',
            'bat_speed': 'BatSpeed',
            'swing_length': 'SwingLength',
            'attack_angle': 'AttackAngle',
            'attack_direction': 'AttackDirection',
            'swing_path_tilt': 'SwingPathTilt',
            'delta_pitcher_run_exp': 'RunExp',
            'estimated_ba_using_speedangle': 'xBA',
            'estimated_slg_using_speedangle': 'xSLG',
            'estimated_woba_using_speedangle': 'xwOBA',
            'woba_value': 'wOBAval',
            'woba_denom': 'wOBAdom',
            'launch_speed_angle': 'Barrel',
        }
        # on_1b/on_2b/on_3b are not renamed — they're consumed to build the Runners column
        runner_cols = ['on_1b', 'on_2b', 'on_3b']

        supplement_display_cols = list(rename_map.values())
        # release_pos_y is used to compute Extension (60.5 - release_pos_y) but is not a display column
        has_release_pos_y = supplement_df is not None and 'release_pos_y' in supplement_df.columns

        if supplement_df is None or supplement_df.empty:
            # Add empty supplement columns so the CSV schema is consistent
            for col in supplement_display_cols:
                if col not in live_df.columns:
                    live_df[col] = np.nan
            # Drop merge keys
            live_df = live_df.drop(columns=['_game_pk', '_at_bat_number', '_pitch_number'])
            return live_df

        # Rename supplement columns to match our naming convention
        supplement_df = supplement_df.rename(columns=rename_map)

        # Rename Statcast merge keys to match the underscore-prefixed live feed keys
        supplement_df = supplement_df.rename(columns={
            'game_pk': '_game_pk',
            'at_bat_number': '_at_bat_number',
            'pitch_number': '_pitch_number',
        })

        merge_keys = ['_game_pk', '_at_bat_number', '_pitch_number']

        merged = live_df.merge(
            supplement_df,
            on=merge_keys,
            how='left',
            suffixes=('', '_statcast')
        )

        # ArmAngle: prefer official Statcast value; fall back to estimate from x0/z0
        if 'ArmAngle_statcast' in merged.columns:
            statcast_aa = pd.to_numeric(merged['ArmAngle_statcast'], errors='coerce')
            estimated_aa = pd.to_numeric(merged['ArmAngle'], errors='coerce')
            merged['ArmAngle'] = statcast_aa.combine_first(estimated_aa).apply(lambda x: f"{x:.1f}" if pd.notna(x) else '')
            merged = merged.drop(columns=['ArmAngle_statcast'])

        # Compute Extension from release_pos_y where available (60.5 - release_pos_y)
        if 'release_pos_y' in merged.columns:
            statcast_ext = 60.5 - pd.to_numeric(merged['release_pos_y'], errors='coerce')
            # Fill in Extension where the live API value was missing, or overwrite with Statcast value
            merged_ext = pd.to_numeric(merged['Extension'], errors='coerce')
            merged['Extension'] = statcast_ext.combine_first(merged_ext).apply(lambda x: f"{x:.2f}" if pd.notna(x) else '')
            merged = merged.drop(columns=['release_pos_y'])

        # Overwrite placeholder columns with Statcast supplement values
        for col in ['RunExp', 'xBA', 'xSLG', 'xwOBA', 'wOBAval', 'wOBAdom']:
            if f'{col}_statcast' in merged.columns:
                merged[col] = pd.to_numeric(merged[f'{col}_statcast'], errors='coerce').apply(lambda x: f"{x:.3f}" if pd.notna(x) else '')
                merged = merged.drop(columns=[f'{col}_statcast'])

        # Build Runners column from on_1b/on_2b/on_3b
        # on_1b/on_2b/on_3b contain player IDs when occupied, NaN when empty
        if all(c in merged.columns for c in runner_cols):
            def _runners_str(row):
                bases = []
                if pd.notna(row.get('on_1b')):
                    bases.append('1')
                if pd.notna(row.get('on_2b')):
                    bases.append('2')
                if pd.notna(row.get('on_3b')):
                    bases.append('3')
                return '+'.join(bases) if bases else '0'
            merged['Runners'] = merged.apply(_runners_str, axis=1)
            merged = merged.drop(columns=runner_cols)

        # Barrel column: keep raw launch_speed_angle value (1-6 scale)
        # If Statcast supplement provided a value, it overwrites the estimate;
        # if only estimate exists, it stays (6 for barrel, empty for non-barrel)
        if 'Barrel_statcast' in merged.columns:
            # Statcast official value takes priority over estimate
            statcast_barrel = pd.to_numeric(merged['Barrel_statcast'], errors='coerce')
            merged['Barrel'] = statcast_barrel.combine_first(
                pd.to_numeric(merged['Barrel'], errors='coerce')
            )
            merged = merged.drop(columns=['Barrel_statcast'])
        # Convert to nullable integer (blanks stay blank, values stay as ints)
        if 'Barrel' in merged.columns:
            merged['Barrel'] = pd.to_numeric(merged['Barrel'], errors='coerce').astype('Int64')

        # Filter out sub-50 BatSpeed (check swings / artifacts)
        if 'BatSpeed' in merged.columns:
            merged['BatSpeed'] = pd.to_numeric(merged['BatSpeed'], errors='coerce')
            merged.loc[merged['BatSpeed'] < 50, 'BatSpeed'] = np.nan

        # Count successful merges
        supplement_value_cols = [c for c in supplement_display_cols if c in merged.columns]
        if supplement_value_cols:
            matched = merged[supplement_value_cols[0]].notna().sum()
            print(f"Statcast supplement merged: {matched}/{len(merged)} pitches matched")

        # Format supplement-only columns with trailing zeros
        supplement_round_1 = ['BatSpeed', 'SwingLength', 'AttackAngle',
                              'AttackDirection', 'SwingPathTilt', 'EffectiveVelo']
        for col in supplement_round_1:
            if col in merged.columns:
                merged[col] = pd.to_numeric(merged[col], errors='coerce').apply(lambda x: f"{x:.1f}" if pd.notna(x) else '')

        # Drop merge keys so they don't appear in the final CSV
        merged = merged.drop(columns=merge_keys)

        return merged

    def download_savant_bat_speed(self, game_pk):
        """
        Download bat speed from the Baseball Savant game feed API.
        Available in near real-time (same day, after game completes).
        Returns a dict keyed by (game_pk, at_bat_number, pitch_number) -> bat_speed value.
        """
        print(f"  Fetching bat speed from Savant game feed for {game_pk}...")
        url = f"https://baseballsavant.mlb.com/gf?game_pk={game_pk}"

        try:
            response = self.session.get(url, timeout=30)
            if response.status_code != 200:
                print(f"  Savant game feed returned status {response.status_code}")
                return {}

            data = response.json()
            lookup = {}

            # Bat speed is in team_away and team_home pitch arrays
            for side in ['team_away', 'team_home']:
                pitches = data.get(side, [])
                for p in pitches:
                    bs = p.get('batSpeed')
                    if bs is not None:
                        bs_val = round(float(bs), 1)
                        if bs_val >= 50:  # Filter out check swings / artifacts
                            key = (str(game_pk), str(p.get('ab_number', '')), str(p.get('pitch_number', '')))
                            lookup[key] = bs_val

            print(f"  Got bat speed for {len(lookup)} swings")
            return lookup

        except Exception as e:
            print(f"  Error fetching Savant game feed: {e}")
            return {}

    def merge_bat_speed(self, df, game_pk):
        """
        Merge bat speed from Savant game feed into the DataFrame.
        Only fills BatSpeed where it's currently empty/NaN.
        """
        lookup = self.download_savant_bat_speed(game_pk)
        if not lookup:
            return df

        filled = 0
        for idx, row in df.iterrows():
            if pd.notna(row.get('BatSpeed')):
                continue  # Already has bat speed (shouldn't happen on fresh download)
            pid = row.get('PitchID', '')
            parts = pid.split('_')
            if len(parts) == 3:
                key = (parts[0], parts[1].lstrip('0') or '0', parts[2].lstrip('0') or '0')
                if key in lookup:
                    bs = lookup[key]
                    if bs >= 50:
                        df.at[idx, 'BatSpeed'] = bs
                    filled += 1

        if filled:
            print(f"  Merged bat speed for {filled} pitches")
        return df

    def download_team_games(self, team_abbrev, start_date, end_date, pitchers_only=False):
        """
        Download all games for a specific team within a date range and save as a single CSV.
        Combines live feed data with Statcast Search supplement.
        """
        # Get all games for the team within the date range
        game_pks = self.get_team_games(team_abbrev, start_date, end_date)

        if not game_pks:
            print(f"No games found for {team_abbrev} from {start_date} to {end_date}")
            return None

        # Download and process each game into DataFrames
        all_dfs = []
        for game_pk in game_pks:
            # Set filter_team parameter if pitchers_only is True
            filter_team = team_abbrev if pitchers_only else None

            # Download game data as DataFrame
            df = self.download_game_data(game_pk, filter_team)

            if df is not None:
                # Fetch real-time bat speed from Savant game feed
                df = self.merge_bat_speed(df, game_pk)
                all_dfs.append(df)
                print(f"Successfully downloaded data for game {game_pk}")
            else:
                print(f"Failed to download data for game {game_pk}")

            # Add a small delay to avoid rate limiting
            time.sleep(1)

        print(f"Downloaded {len(all_dfs)} out of {len(game_pks)} games for {team_abbrev}")

        # If no games were downloaded, return None
        if not all_dfs:
            print(f"Failed to download any games for {team_abbrev}")
            return None

        # Combine all downloaded games into a single DataFrame
        combined_df = pd.concat(all_dfs, ignore_index=True)

        # Attempt to merge Statcast Search supplement data
        print("\nAttempting Statcast Search supplement download...")
        supplement_df = self.download_statcast_supplement(team_abbrev, start_date, end_date)
        combined_df = self.merge_statcast_supplement(combined_df, supplement_df)

        # Enforce final column order
        final_columns = [
            'Game Date', 'PTeam', 'Pitcher', 'Throws', 'Pitch Type',
            'Velocity', 'Spin Rate', 'RTilt', 'OTilt', 'IndVertBrk', 'HorzBrk',
            'xIndVrtBrk', 'xHorzBrk',
            'RelPosZ', 'RelPosX', 'Extension', 'ArmAngle', 'EffectiveVelo',
            'PlateZ', 'PlateX', 'SzTop', 'SzBot',
            'VAA', 'HAA', 'PlateTime',
            'BTeam', 'Batter', 'Bats', 'Count', 'Runners', 'Outs',
            'Description', 'Event',
            'ExitVelo', 'LaunchAngle', 'Distance', 'BBType',
            'HC_X', 'HC_Y', 'xBA', 'xSLG', 'xwOBA', 'wOBAval', 'wOBAdom', 'RunExp',
            'BatSpeed', 'SwingLength',
            'AttackAngle', 'AttackDirection', 'SwingPathTilt',
            'PitchID',
            'Barrel',
        ]

        # Only include columns that exist
        final_columns = [c for c in final_columns if c in combined_df.columns]
        combined_df = combined_df[final_columns]

        # Save the combined data directly to the team file
        output_filename = os.path.join(self.download_dir, f"{team_abbrev}.csv")
        combined_df.to_csv(output_filename, index=False)

        print(f"\nCombined {len(all_dfs)} games with {len(combined_df)} total pitches")
        print(f"Combined data saved to: {output_filename}")

        return output_filename

    def download_games_by_id(self, game_pks, filter_team=None, output_name=None):
        """
        Download one or more games by their game PK IDs and save as a single CSV.

        Useful for games involving national teams or other non-MLB teams that
        don't have entries in the team abbreviation/ID mappings.

        Args:
            game_pks: A single game PK (int) or a list of game PKs
            filter_team: Optional team name/abbreviation to filter pitchers by.
                         Must match exactly what the API returns as the team
                         abbreviation (e.g., "TOR", "CAN"). If unsure, run
                         once without filter_team to see what team names appear
                         in the PTeam column, then re-run with the correct value.
            output_name: Optional filename stem for the output CSV.
                         Defaults to the game PK (single game) or "custom" (multiple).
        """
        # Accept a single game PK or a list
        if isinstance(game_pks, (int, str)):
            game_pks = [int(game_pks)]
        else:
            game_pks = [int(pk) for pk in game_pks]

        print(f"Downloading {len(game_pks)} game(s) by ID: {game_pks}")
        if filter_team:
            print(f"Filtering to pitchers from: {filter_team}")

        all_dfs = []
        for game_pk in game_pks:
            df = self.download_game_data(game_pk, filter_team)

            if df is not None:
                all_dfs.append(df)
                print(f"Successfully downloaded data for game {game_pk}")
            else:
                print(f"Failed to download data for game {game_pk}")

            # Add a small delay between games to avoid rate limiting
            if len(game_pks) > 1:
                time.sleep(1)

        if not all_dfs:
            print("Failed to download any games")
            return None

        combined_df = pd.concat(all_dfs, ignore_index=True)

        # No Statcast supplement for game-ID mode (no team for query),
        # but still need to drop merge keys and ensure schema consistency
        combined_df = self.merge_statcast_supplement(combined_df, None)

        # Enforce final column order
        final_columns = [
            'Game Date', 'PTeam', 'Pitcher', 'Throws', 'Pitch Type',
            'Velocity', 'Spin Rate', 'RTilt', 'OTilt', 'IndVertBrk', 'HorzBrk',
            'xIndVrtBrk', 'xHorzBrk',
            'RelPosZ', 'RelPosX', 'Extension', 'ArmAngle', 'EffectiveVelo',
            'PlateZ', 'PlateX', 'SzTop', 'SzBot',
            'VAA', 'HAA', 'PlateTime',
            'BTeam', 'Batter', 'Bats', 'Count', 'Runners', 'Outs',
            'Description', 'Event',
            'ExitVelo', 'LaunchAngle', 'Distance', 'BBType',
            'HC_X', 'HC_Y', 'xBA', 'xSLG', 'xwOBA', 'wOBAval', 'wOBAdom', 'RunExp',
            'BatSpeed', 'SwingLength',
            'AttackAngle', 'AttackDirection', 'SwingPathTilt',
            'PitchID',
            'Barrel',
        ]
        final_columns = [c for c in final_columns if c in combined_df.columns]
        combined_df = combined_df[final_columns]

        # Determine output filename
        if output_name:
            stem = output_name
        elif len(game_pks) == 1:
            stem = str(game_pks[0])
        else:
            stem = "custom"

        output_filename = os.path.join(self.download_dir, f"{stem}.csv")
        combined_df.to_csv(output_filename, index=False)

        print(f"\nCombined {len(all_dfs)} games with {len(combined_df)} total pitches")
        print(f"Data saved to: {output_filename}")

        return output_filename


def main():
    """Main function to download pitcher data"""

    # ── Settings (edit these directly or override via command line) ──
    team_abbrev     = "SDP"
    start_date      = "2026-04-25"
    end_date        = "2026-04-25"
    pitchers_only   = True

    game_id         = ""          # Game PK (e.g., "831437") — leave blank for team/date lookup
    filter_team     = None        # Optional team filter for game ID mode (e.g., "CAN")
    output_name     = ""          # Optional custom filename (without .csv)

    # ── CLI overrides (optional — values above are used if no args passed) ──
    parser = argparse.ArgumentParser(description='Download pitch data from Baseball Savant')
    parser.add_argument('--team', default=None, help='Team abbreviation')
    parser.add_argument('--start', default=None, help='Start date YYYY-MM-DD')
    parser.add_argument('--end', default=None, help='End date YYYY-MM-DD')
    parser.add_argument('--pitchers-only', dest='pitchers_only', action='store_true', default=None)
    parser.add_argument('--no-pitchers-only', dest='pitchers_only', action='store_false')
    parser.add_argument('--game-id', default=None, help='Game PK (e.g., 831437)')
    parser.add_argument('--filter-team', default=None, help='Team filter for game ID mode')
    parser.add_argument('--output-name', default=None, help='Custom filename (without .csv)')
    args = parser.parse_args()

    if args.team is not None: team_abbrev = args.team
    if args.start is not None: start_date = args.start
    if args.end is not None: end_date = args.end
    if args.pitchers_only is not None: pitchers_only = args.pitchers_only
    if args.game_id is not None: game_id = args.game_id
    if args.filter_team is not None: filter_team = args.filter_team
    if args.output_name is not None: output_name = args.output_name

    downloader = BaseballSavantFocusedDownloader()

    # ── Logic: game_id takes priority, otherwise fall back to team/date lookup ──
    if game_id:
        result = downloader.download_games_by_id(
            game_pks=game_id,
            filter_team=filter_team,
            output_name=output_name if output_name else None,
        )

        if result:
            print(f"\nData saved to: {result}")
        else:
            print("\nFailed to download game data")

    elif team_abbrev:
        result = downloader.download_team_games(team_abbrev, start_date, end_date, pitchers_only)

        if result:
            print(f"\nSuccessfully downloaded and combined games for {team_abbrev}")
            print(f"Data saved to: {result}")
        else:
            print(f"\nFailed to download any games for {team_abbrev}")

    else:
        print("Error: Please set either game_id or team_abbrev")


if __name__ == "__main__":
    main()