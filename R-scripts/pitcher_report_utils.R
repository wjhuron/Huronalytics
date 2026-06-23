# pitcher_report_utils.R — Shared utilities for OnePitcher.R, Season.R, and Daily.R
# Sourced by each script to avoid duplication.

# ---- Pitch Type Definitions ----

# Mapping from pitch-type codes to display names
pitch_names <- c(
  "FF" = "Fastball",
  "SI" = "Sinker",
  "CF" = "Cut-Fastball",
  "CU" = "Curveball",
  "SV" = "Slurve",
  "SL" = "Slider",
  "ST" = "Sweeper",
  "CH" = "Changeup",
  "FS" = "Splitter",
  "FC" = "Cutter",
  "KN" = "Knuckleball",
  "EP" = "Eephus"
)

# Colors for pitch-type visualizations
pitch_colors <- c(
  "FF" = "blue",
  "SI" = "gold1",
  "CF" = "saddlebrown",
  "FC" = "orange",
  "CU" = "firebrick3",
  "SL" = "darkgreen",
  "SV" = "limegreen",
  "ST" = "deeppink",
  "CH" = "purple",
  "FS" = "turquoise",
  "KN" = "black",
  "EP" = "gray50"
)

# Display order for pitch types
pitch_order <- c(
  "Fastball", "Sinker", "Cut-Fastball", "Cutter",
  "Slider", "Sweeper", "Curveball", "Slurve",
  "Changeup", "Splitter", "Knuckleball"
)

# ---- Team / League Lookup ----

TEAM_LEAGUE <- c(
  ATH = "AL", BAL = "AL", BOS = "AL", CLE = "AL", CWS = "AL",
  DET = "AL", HOU = "AL", KCR = "AL", LAA = "AL", MIN = "AL",
  NYY = "AL", SEA = "AL", TBR = "AL", TEX = "AL", TOR = "AL",
  ARI = "NL", ATL = "NL", CHC = "NL", CIN = "NL", COL = "NL",
  LAD = "NL", MIA = "NL", MIL = "NL", NYM = "NL", PHI = "NL",
  PIT = "NL", SDP = "NL", SFG = "NL", STL = "NL", WSH = "NL",
  ROC = "NL", AAA = "NL", FCL = "NL"
)

# Build the full CSV path from just a team code.
# Usage: resolve_team_path("PIT")  =>  "/Users/wallyhuron/Downloads/NL 2026 - PIT.csv"
#        resolve_team_path("/Users/wallyhuron/Downloads/NL 2026 - PIT.csv")  =>  unchanged
resolve_team_path <- function(input, year = 2026, base_dir = "/Users/wallyhuron/Downloads/") {
  # If it already looks like a full path, return as-is
  if (grepl("/", input) || grepl("\\.csv$", input, ignore.case = TRUE)) {
    return(input)
  }
  # Treat input as a team code
  team <- toupper(trimws(input))
  league <- TEAM_LEAGUE[team]
  if (is.na(league)) stop("Unknown team code: ", team, ". Expected one of: ", paste(names(TEAM_LEAGUE), collapse = ", "))
  paste0(base_dir, league, " ", year, " - ", team, ".csv")
}

# ---- Supabase (Postgres) data source ----
# During the Sheets -> Supabase migration, team data is read from the Supabase
# `pitches` table instead of per-team CSV exports. read_team_from_supabase()
# returns a tibble byte-identical to the old
#   read_csv("<LG> <YR> - <TEAM>.csv", col_types = cols(OTilt = col_character()))
# by round-tripping the query result through a temp CSV, so readr infers the
# exact same column types it always did.

# Canonical 47 columns, in Sheet order (must match supabase_append.COLUMNS).
SUPABASE_COLUMNS <- c(
  "Game Date", "PTeam", "Pitcher", "Throws", "Pitch Type", "Velocity",
  "Spin Rate", "RTilt", "OTilt", "IndVertBrk", "HorzBrk", "xIndVrtBrk",
  "xHorzBrk", "RelPosZ", "RelPosX", "Extension", "ArmAngle", "PlateZ", "PlateX",
  "SzTop", "SzBot", "VAA", "HAA", "BTeam", "Batter", "Bats", "Count", "Runners",
  "Outs", "Description", "Event", "ExitVelo", "LaunchAngle", "Distance",
  "BBType", "HC_X", "HC_Y", "xBA", "xSLG", "xwOBA", "RunExp", "BatSpeed",
  "SwingLength", "AttackAngle", "AttackDirection", "SwingPathTilt", "PitchID"
)

# Read SUPABASE_DB_URL from the environment, falling back to the repo .env file.
.read_supabase_url <- function() {
  url <- Sys.getenv("SUPABASE_DB_URL", "")
  if (nzchar(url)) return(url)
  env_path <- Sys.getenv("HURONALYTICS_ENV", "/Users/wallyhuron/Huronalytics/.env")
  if (file.exists(env_path)) {
    lines <- readLines(env_path, warn = FALSE)
    hit <- grep("^SUPABASE_DB_URL=", lines, value = TRUE)
    if (length(hit) > 0) {
      val <- sub("^SUPABASE_DB_URL=", "", hit[[1]])
      return(trimws(gsub('^["\']|["\']$', "", val)))
    }
  }
  stop("SUPABASE_DB_URL not found in environment or ", env_path)
}

# Parse a postgres URL into its connection components.
.parse_pg_url <- function(url) {
  m <- regmatches(url, regexec(
    "^postgres(?:ql)?://([^:]+):(.+)@([^:@/]+):([0-9]+)/([^?]+)", url))[[1]]
  if (length(m) != 6) stop("Could not parse SUPABASE_DB_URL")
  list(user = m[[2]], password = m[[3]], host = m[[4]],
       port = as.integer(m[[5]]), dbname = m[[6]])
}

# Open a DBI connection to the Supabase Postgres (TLS required).
supabase_connect <- function() {
  if (!requireNamespace("DBI", quietly = TRUE) ||
      !requireNamespace("RPostgres", quietly = TRUE)) {
    stop("DBI and RPostgres are required to read from Supabase. ",
         "Install with: install.packages(c('DBI','RPostgres'))")
  }
  p <- .parse_pg_url(.read_supabase_url())
  DBI::dbConnect(RPostgres::Postgres(),
                 host = p$host, port = p$port, dbname = p$dbname,
                 user = p$user, password = p$password, sslmode = "require")
}

# Read one team's pitches from Supabase. Returns a tibble identical to the old
# per-team CSV read (same columns, types, and values).
read_team_from_supabase <- function(team) {
  con <- supabase_connect()
  on.exit(DBI::dbDisconnect(con), add = TRUE)
  # Each team is its own table (matches supabase_append.table_for_team()).
  tbl <- gsub("[^A-Z0-9_]", "_", toupper(trimws(team)))
  collist <- paste(sprintf('"%s"', SUPABASE_COLUMNS), collapse = ", ")
  q <- sprintf('SELECT %s FROM "%s" ORDER BY id', collist, tbl)
  df <- DBI::dbGetQuery(con, q)
  # Round-trip through a temp CSV so readr guesses column types EXACTLY as the
  # old read_csv(... cols(OTilt = col_character())) path did.
  tmp <- tempfile(fileext = ".csv")
  on.exit(unlink(tmp), add = TRUE)
  readr::write_csv(df, tmp, na = "")
  readr::read_csv(tmp, col_types = readr::cols(OTilt = readr::col_character()))
}

# Extract a team code from a bare code ("PIT") or a CSV path
# (".../NL 2026 - PIT.csv" -> "PIT"). Returns NA if none can be derived.
extract_team_code <- function(input) {
  s <- trimws(input)
  if (grepl("\\.csv$", s, ignore.case = TRUE)) {
    base <- sub("\\.csv$", "", basename(s), ignore.case = TRUE)
    if (grepl(" - ", base)) return(toupper(trimws(sub(".* - ", "", base))))
    return(NA_character_)
  }
  toupper(s)
}

# Load a team's pitch data. Known team codes (and the team-CSV filename pattern
# produced by resolve_team_path) read from Supabase; any other existing .csv
# path still reads from disk, so ad-hoc CSV files keep working unchanged.
load_pitch_data <- function(input) {
  team <- extract_team_code(input)
  if (!is.na(team) && team %in% names(TEAM_LEAGUE)) {
    return(read_team_from_supabase(team))
  }
  if (file.exists(input)) {
    return(readr::read_csv(input, col_types = readr::cols(OTilt = readr::col_character())))
  }
  stop("load_pitch_data: '", input,
       "' is neither a known team code nor an existing CSV file")
}

# ---- Shared Helper Functions ----

# Compute InZone from PlateX/PlateZ/SzTop/SzBot with ball-radius adjustment
# Matches the formula in process_data.py:
#   BALL_RADIUS_FT = 1.45 / 12  (~0.121 ft)
#   ZONE_HALF_WIDTH = 0.83  (half plate 8.5" + ball radius 1.45" in feet)
#   InZone = "Yes" if abs(PlateX) <= 0.83 AND (SzBot - radius) <= PlateZ <= (SzTop + radius)
compute_in_zone <- function(plate_x, plate_z, sz_top, sz_bot) {
  ball_radius <- 1.45 / 12  # ~0.121 ft
  zone_half_width <- 0.83
  case_when(
    is.na(plate_x) | is.na(plate_z) | is.na(sz_top) | is.na(sz_bot) ~ NA_character_,
    abs(plate_x) <= zone_half_width &
      plate_z >= (sz_bot - ball_radius) &
      plate_z <= (sz_top + ball_radius) ~ "Yes",
    TRUE ~ "No"
  )
}

# Helper: average clock-format tilt strings (e.g., "1:54", "12:30")
# Converts H:MM to total minutes on a 12-hour clock, averages circularly, converts back
avg_tilt_clock <- function(tilts) {
  tilts <- na.omit(tilts)
  tilts <- tilts[tilts != ""]
  if (length(tilts) == 0) return(NA_character_)

  # Parse "H:MM" to total minutes (0-720 for 12-hour clock)
  parsed <- sapply(tilts, function(t) {
    parts <- strsplit(as.character(t), ":")[[1]]
    if (length(parts) != 2) return(NA_real_)
    h <- as.numeric(parts[1])
    m <- as.numeric(parts[2])
    if (is.na(h) || is.na(m)) return(NA_real_)
    # Normalize 12 to 0 for circular math
    if (h == 12) h <- 0
    h * 60 + m
  }, USE.NAMES = FALSE)

  parsed <- parsed[!is.na(parsed)]
  if (length(parsed) == 0) return(NA_character_)

  # Circular mean on a 720-minute (12-hour) clock
  angles <- parsed * 2 * pi / 720
  avg_sin <- mean(sin(angles))
  avg_cos <- mean(cos(angles))
  avg_angle <- atan2(avg_sin, avg_cos)
  avg_minutes <- (avg_angle * 720 / (2 * pi)) %% 720

  # Convert back to H:MM
  h <- floor(avg_minutes / 60)
  m <- round(avg_minutes %% 60)
  if (m == 60) { h <- h + 1; m <- 0 }
  if (h == 0) h <- 12
  sprintf("%d:%02d", h, m)
}

# Helper: check if a column has real data for a given pitcher
col_has_data <- function(data, pitcher_name, col_name) {
  if (!(col_name %in% names(data))) return(FALSE)
  pitcher_data <- data %>% filter(Pitcher == pitcher_name)
  any(!is.na(pitcher_data[[col_name]]))
}
