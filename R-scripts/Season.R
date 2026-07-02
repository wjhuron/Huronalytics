# ---- Configuration ----
input_file_path <- "TBR"  # Team code (e.g., "PIT", "WSH") or full path
output_directory <- "/Users/wallyhuron/Downloads/"

# ---- Optional Filtering Parameters ----
# Set these to NULL to disable filtering
selected_pitcher_filter <- NULL  # Example format: "Bieber, Shane" 
start_date_filter <- NULL        # Example format: "2025-04-01"
end_date_filter <- NULL          # Example format: "2025-04-20"

# ---- Required Libraries ----
library(tidyverse)
library(patchwork)
library(gridExtra)
library(gtable)
library(grid)
library(cowplot)

# Source shared utilities (pitch_names, pitch_colors, pitch_order, compute_in_zone, avg_tilt_clock, col_has_data)
source("/Users/wallyhuron/Huronalytics/R-scripts/pitcher_report_utils.R")

# Allow command-line overrides: Rscript Season.R "/path/to/file.csv" "2026-04-01" "2026-04-08" "Bieber, Shane"
cli_args <- commandArgs(trailingOnly = TRUE)
if (length(cli_args) >= 1) input_file_path <- cli_args[1]
if (length(cli_args) >= 2) start_date_filter <- cli_args[2]
if (length(cli_args) >= 3) end_date_filter <- cli_args[3]
if (length(cli_args) >= 4) selected_pitcher_filter <- cli_args[4]

# Resolve team code to full path (e.g., "PIT" -> "/Users/wallyhuron/Downloads/NL 2026 - PIT.csv")
input_file_path <- resolve_team_path(input_file_path)

# ---- Data Processing Functions ----

# Function to calculate combined pitcher stats (Table 1 metrics)
calculate_combined_pitcher_stats <- function(data, pitcher_name, has_arm_angle = FALSE) {
  
  pitcher_data <- data %>%
    filter(Pitcher == pitcher_name)
  
  total_pitches <- nrow(pitcher_data)
  
  # Define pitch outcome event categories (simplified descriptions)
  swing_events <- c("Swinging Strike", "Foul", "In Play")
  csw_events <- c("Called Strike", "Swinging Strike")
  swstr_events <- c("Swinging Strike")
  in_play_events <- c("In Play")
  
  result <- pitcher_data %>%
    group_by(`Pitch Type`) %>%
    summarize(
      num_thrown = sprintf("%.0f", n()),
      percent_thrown = sprintf("%.1f%%", n() / total_pitches * 100),
      avg_velo = sprintf("%.1f mph", mean(Velocity, na.rm = TRUE)),
      max_velo = sprintf("%.1f mph", max(Velocity, na.rm = TRUE)),
      avg_spin = sprintf("%.0f rpm", round(mean(`Spin Rate`, na.rm = TRUE))),
      avg_tilt = avg_tilt_clock(OTilt),
      avg_ivb = sprintf("%.1f\"", mean(xIndVrtBrk, na.rm = TRUE)),
      avg_hb = sprintf("%.1f\"", mean(xHorzBrk, na.rm = TRUE)),
      avg_height = sprintf("%.2f'", mean(RelPosZ, na.rm = TRUE)),
      avg_side = sprintf("%.2f'", mean(RelPosX, na.rm = TRUE)),
      avg_extension = sprintf("%.2f'", mean(Extension, na.rm = TRUE)),
      avg_arm_angle = if (has_arm_angle) sprintf("%.1f°", mean(ArmAngle, na.rm = TRUE)) else NA_character_,
      avg_vaa = sprintf("%.2f°", mean(VAA, na.rm = TRUE)),
      avg_haa = sprintf("%.2f°", mean(HAA, na.rm = TRUE)),
      # Table 2 metrics
      iz_percent = sprintf("%.1f%%", sum(InZone == "Yes", na.rm = TRUE) / n() * 100),
      csw_percent = sprintf("%.1f%%", sum(Description %in% csw_events, na.rm = TRUE) / n() * 100),
      swstr_percent = {
        total_swings <- sum(Description %in% swing_events, na.rm = TRUE)
        if (total_swings > 0) {
          sprintf("%.1f%%", sum(Description %in% swstr_events, na.rm = TRUE) / total_swings * 100)
        } else {
          "---"
        }
      },
      chase_percent = {
        ooz_pitches <- sum(InZone == "No", na.rm = TRUE)
        if (ooz_pitches > 0) {
          sprintf("%.1f%%", sum(Description %in% swing_events & (InZone == "No"), na.rm = TRUE) / ooz_pitches * 100)
        } else {
          "---"
        }
      },
      gb_percent = {
        balls_in_play <- sum(Description %in% in_play_events & !grepl("^bunt", BBType), na.rm = TRUE)
        ground_balls <- sum(Description %in% in_play_events & BBType == "ground_ball", na.rm = TRUE)
        if (balls_in_play > 0) {
          sprintf("%.1f%%", ground_balls / balls_in_play * 100)
        } else {
          sprintf("%.1f%%", 0)
        }
      },
      .groups = "drop"
    )
  
  # Select columns based on whether arm angle data exists
  if (has_arm_angle) {
    result %>%
      select(
        `Pitch Type`, num_thrown, percent_thrown, avg_velo, max_velo, avg_spin, avg_tilt,
        avg_ivb, avg_hb, avg_height, avg_side, avg_extension, avg_arm_angle, 
        avg_vaa, avg_haa,
        iz_percent, csw_percent, swstr_percent, chase_percent, gb_percent
      )
  } else {
    result %>%
      select(
        `Pitch Type`, num_thrown, percent_thrown, avg_velo, max_velo, avg_spin, avg_tilt,
        avg_ivb, avg_hb, avg_height, avg_side, avg_extension,
        avg_vaa, avg_haa,
        iz_percent, csw_percent, swstr_percent, chase_percent, gb_percent
      )
  }
}

# Function to calculate platoon split stats
calculate_platoon_stats <- function(data, pitcher_name) {
  pitcher_data <- data %>%
    filter(Pitcher == pitcher_name)
  
  # Define pitch outcome event categories (simplified descriptions)
  swing_events <- c("Swinging Strike", "Foul", "In Play")
  csw_events <- c("Called Strike", "Swinging Strike")
  swstr_events <- c("Swinging Strike")
  in_play_events <- c("In Play")
  
  # Calculate total pitches by handedness first
  total_pitches_by_handedness <- pitcher_data %>%
    group_by(Bats) %>%
    summarise(total_pitches = n(), .groups = "drop")

  # Calculate stats by pitch type and batter handedness
  platoon_stats <- pitcher_data %>%
    group_by(`Pitch Type`, Bats) %>%
    summarize(
      num_thrown = n(),
      # IZ% count
      iz_count = sum(InZone == "Yes", na.rm = TRUE),
      swing_count = sum(Description %in% swing_events, na.rm = TRUE),
      csw_count = sum(Description %in% csw_events, na.rm = TRUE),
      swstr_count = sum(Description %in% swstr_events, na.rm = TRUE),
      # Chase count (swings outside zone) and out-of-zone pitch count
      ooz_count = sum(InZone == "No", na.rm = TRUE),
      chase_count = sum(Description %in% swing_events & (InZone == "No"), na.rm = TRUE),
      # Ground Ball calculations
      balls_in_play = sum(Description %in% in_play_events & !grepl("^bunt", BBType), na.rm = TRUE),
      ground_balls = sum(Description %in% in_play_events & BBType == "ground_ball", na.rm = TRUE),
      .groups = "drop"
    ) %>%
    # Join with total pitches by handedness to calculate correct percentages
    left_join(total_pitches_by_handedness, by = "Bats") %>%
    mutate(
      num_thrown_fmt = sprintf("%.0f", num_thrown),
      percent_thrown = sprintf("%.1f%%", (num_thrown / total_pitches) * 100),
      iz_percent = sprintf("%.1f%%", (iz_count / num_thrown) * 100),
      csw_percent = sprintf("%.1f%%", (csw_count / num_thrown) * 100),
      swstr_percent = sprintf("%.1f%%", ifelse(swing_count > 0, (swstr_count / swing_count) * 100, 0)),
      chase_percent = sprintf("%.1f%%", ifelse(ooz_count > 0, (chase_count / ooz_count) * 100, 0)),
      gb_percent = sprintf("%.1f%%", ifelse(balls_in_play > 0, (ground_balls / balls_in_play) * 100, 0))
    ) %>%
    select(`Pitch Type`, Bats, num_thrown_fmt, percent_thrown, iz_percent,
           csw_percent, swstr_percent, chase_percent, gb_percent)

  # Pivot to create side-by-side columns for RHH and LHH
  rhh_stats <- platoon_stats %>%
    filter(Bats == "R") %>%
    select(-Bats) %>%
    rename_with(~paste0(., "_rhh"), -`Pitch Type`)

  lhh_stats <- platoon_stats %>%
    filter(Bats == "L") %>%
    select(-Bats) %>%
    rename_with(~paste0(., "_lhh"), -`Pitch Type`)
  
  # Combine RHH and LHH stats
  combined_platoon <- rhh_stats %>%
    full_join(lhh_stats, by = "Pitch Type") %>%
    replace_na(list(
      num_thrown_fmt_rhh = "0", percent_thrown_rhh = "0.0%", iz_percent_rhh = "0.0%",
      csw_percent_rhh = "0.0%", swstr_percent_rhh = "0.0%", 
      chase_percent_rhh = "0.0%", gb_percent_rhh = "0.0%",
      num_thrown_fmt_lhh = "0", percent_thrown_lhh = "0.0%", iz_percent_lhh = "0.0%",
      csw_percent_lhh = "0.0%", swstr_percent_lhh = "0.0%",
      chase_percent_lhh = "0.0%", gb_percent_lhh = "0.0%"
    ))
  
  return(combined_platoon)
}

# ---- Visualization Functions ----
# Helper function to format tables consistently
format_table <- function(tbl, stats_df, pitch_names) {
  # Find indices of core-bg cells and core-fg cells (for text)
  bg_indices <- which(tbl$layout$name == "core-bg")
  fg_indices <- which(tbl$layout$name == "core-fg")
  
  # Color mapping for pitch types
  pitch_colors <- list(
    "FF" = list(fill = alpha("#0086D2"), text = "white"),
    "SL" = list(fill = alpha("#FB6E00"), text = "white"),
    "ST" = list(fill = alpha("#35B6FF"), text = "black"),
    "CU" = list(fill = alpha("#230AA0"), text = "white"),
    "FC" = list(fill = alpha("#A45B16"), text = "white"),
    "SI" = list(fill = alpha("#FFB500"), text = "black"),
    "CH" = list(fill = alpha("#00BA87"), text = "white"),
    "FS" = list(fill = alpha("#F076BA"), text = "black"),
    "KN" = list(fill = alpha("black"), text = "white"),
    "SV" = list(fill = alpha("#A00A55"), text = "white"),
    "EP" = list(fill = alpha("gray50"), text = "white")
  )
  
  # Color the backgrounds and text for first column cells
  for (i in seq_len(nrow(stats_df))) {
    pitch_full <- stats_df[[1]][i]  # First column (Pitch Type)
    # Find the first matching pitch code
    pitch_code <- names(which(pitch_names == pitch_full))[1]
    
    # Only proceed if we found a matching pitch code
    if (!is.na(pitch_code) && pitch_code %in% names(pitch_colors)) {
      color_info <- pitch_colors[[pitch_code]]
      tbl$grobs[[bg_indices[i]]]$gp$fill <- color_info$fill
      tbl$grobs[[fg_indices[i]]]$gp$col <- color_info$text
    }
  }
  
  # For platoon table, also color the second pitch type column
  if (ncol(stats_df) >= 16) {  # This is the platoon table
    for (i in seq_len(nrow(stats_df))) {
      pitch_full <- stats_df[[9]][i]  # 9th column (second Pitch Type)
      pitch_code <- names(which(pitch_names == pitch_full))[1]
      
      if (!is.na(pitch_code) && pitch_code %in% names(pitch_colors)) {
        color_info <- pitch_colors[[pitch_code]]
        # Color the 9th column background and text
        col_offset <- 8 * nrow(stats_df)
        if (length(bg_indices) > (i + col_offset - 1)) {
          tbl$grobs[[bg_indices[i + col_offset]]]$gp$fill <- color_info$fill
          tbl$grobs[[fg_indices[i + col_offset]]]$gp$col <- color_info$text
        }
      }
    }
  }
  
  # Add borders to all cells
  tbl <- gtable::gtable_add_grob(
    tbl,
    grobs = rectGrob(gp = gpar(fill = NA, col = "black")),
    t = 1, b = nrow(tbl), l = 1, r = ncol(tbl)
  )
  
  # Add internal borders
  for (i in 1:nrow(tbl)) {
    tbl <- gtable::gtable_add_grob(
      tbl,
      grobs = rectGrob(gp = gpar(fill = NA, col = "black")),
      t = i, b = i, l = 1, r = ncol(tbl)
    )
  }
  
  for (j in 1:ncol(tbl)) {
    tbl <- gtable::gtable_add_grob(
      tbl,
      grobs = rectGrob(gp = gpar(fill = NA, col = "black")),
      t = 1, b = nrow(tbl), l = j, r = j
    )
  }
  
  # Force consistent header formatting
  for (i in seq_along(names(stats_df))) {
    header_indices <- which(grepl("colhead", tbl$layout$name))
    if (length(header_indices) >= i) {
      tbl$grobs[[header_indices[i]]]$gp <- 
        gpar(col = "black", fontface = "bold", fontsize = 9)
    }
  }
  
  return(tbl)
}

# Function to create pitch movement plot
create_pitch_plot <- function(pitch_data_filtered, pitcher_name, game_date = NULL) {
  # Format pitcher name for title
  pitcher_name_fmt <- str_replace(pitcher_name, "(.*), (.*)", "\\2 \\1")
  
  # Create the title with explicit date formatting
  if (is.null(game_date)) {
    title_text <- paste(pitcher_name_fmt, "Pitch Movement")
  } else {
    title_text <- paste0(pitcher_name_fmt, " Pitch Movement ", as.character(game_date))
  }
  
  # Calculate average arm angle for each pitch type for arm angle lines
  arm_angle_data <- pitch_data_filtered %>%
    group_by(`Pitch Type`) %>%
    summarise(avg_arm_angle = mean(ArmAngle, na.rm = TRUE), .groups = "drop") %>%
    filter(!is.na(avg_arm_angle))
  
  # Determine if pitcher is RHP or LHP based on average arm side release
  avg_arm_side <- mean(pitch_data_filtered$RelPosX, na.rm = TRUE)
  is_rhp <- avg_arm_side < 0  # RHP have negative RelPosX
  
  # Create arm angle line data
  
  arm_angle_segments <- data.frame()
  line_length <- 30  # Adjust this value to change line length
  
  # Only process arm angles if we have valid data
  if (nrow(arm_angle_data) > 0) {
    for (i in 1:nrow(arm_angle_data)) {
      pitch_type_current <- arm_angle_data$`Pitch Type`[i]
      arm_angle_deg <- arm_angle_data$avg_arm_angle[i]
      
      # Skip if arm_angle_deg is NA (extra safety check)
      if (is.na(arm_angle_deg)) {
        next
      }
      
      arm_angle_rad <- arm_angle_deg * pi / 180
      
      # Calculate slope from arm angle
      slope <- tan(arm_angle_rad)
      
      if (is_rhp) {
        # For RHP: Q1 (positive x, positive y) and Q4 (positive x, negative y)
        x_end <- line_length / sqrt(1 + slope^2)
        y_end <- slope * x_end
      } else {
        # For LHP: 
        # If arm angle is positive -> Q2 (negative x, positive y)
        # If arm angle is negative -> Q3 (negative x, negative y)
        if (arm_angle_deg > 0) {
          # Positive angle: line goes to Q2
          x_end <- -line_length / sqrt(1 + slope^2)
          y_end <- abs(slope * x_end)  # Ensure positive y
        } else {
          # Negative angle: line goes to Q3
          x_end <- -line_length / sqrt(1 + slope^2)
          y_end <- -abs(slope * x_end)  # Ensure negative y
        }
      }
      
      # Add segment data
      arm_angle_segments <- rbind(arm_angle_segments, 
                                  data.frame(x = 0, y = 0, xend = x_end, yend = y_end, 
                                             `Pitch Type` = pitch_type_current, check.names = FALSE))
    }
  }
  
  # Create the base plot
  p <- ggplot(
    pitch_data_filtered, 
    aes(x = xHorzBrk, y = xIndVrtBrk, color = `Pitch Type`, fill = `Pitch Type`)
  ) +
    geom_hline(yintercept = 0, color = "black", linetype = "dashed", linewidth = 0.5) +  
    geom_vline(xintercept = 0, color = "black", linetype = "dashed", linewidth = 0.5)
  
  # Only add arm angle lines if we have data for them
  if (nrow(arm_angle_segments) > 0) {
    p <- p + geom_segment(data = arm_angle_segments,
                          aes(x = x, y = y, xend = xend, yend = yend, color = `Pitch Type`),
                          linetype = "longdash", 
                          alpha = 1, 
                          linewidth = 0.8,
                          inherit.aes = FALSE)
  }
  
  # Add the rest of the plot elements
  p <- p +
    stat_ellipse(geom = "polygon", alpha = 0, level = 0.68, type = "norm", linetype = "longdash") +
    geom_point(size = 3.5, alpha = 1) +
    scale_color_manual(values = pitch_colors) +
    scale_fill_manual(values = pitch_colors) +
    scale_x_continuous(breaks = c(-25, -20, -15, -10, -5, 0, 5, 10, 15, 20, 25)) +
    scale_y_continuous(breaks = c(-25, -20, -15, -10, -5, 0, 5, 10, 15, 20, 25)) +
    labs(
      title = title_text,
      x = "Horizontal Break (in.)",
      y = "Induced Vertical Break (in.)"
    ) +
    coord_cartesian(xlim = c(-25, 25), ylim = c(-25, 25)) +  
    theme_minimal(base_size = 5) +
    theme(
      plot.background = element_rect(fill = "white", color = NA),
      panel.background = element_rect(fill = "white", color = NA),
      panel.grid.major = element_line(color = "gray90", linewidth = 0.3),
      panel.border = element_rect(color = "black", fill = NA, linewidth = 0.5),
      legend.position = "bottom",
      legend.background = element_rect(fill = "white"),
      plot.title = element_text(face = "bold", hjust = 0.5, size = 24),
      axis.title = element_text(size = 16),
      axis.text = element_text(size = 10),
      plot.margin = margin(t = 20, r = 10, b = 10, l = 10, unit = "pt")
    )
  
  return(p)
}

# Modified function to create both main stats table and platoon splits table
create_pitcher_tables <- function(pitch_data, selected_pitcher, game_date = NULL) {
  # Filter by date if provided
  if (!is.null(game_date)) {
    pitch_data <- pitch_data %>% 
      filter(`Game Date` == game_date)
  }
  
  # Check if Arm Angle column exists and has data for this pitcher
  has_arm_angle <- "ArmAngle" %in% names(pitch_data) && 
    any(!is.na(pitch_data$ArmAngle[pitch_data$Pitcher == selected_pitcher]))
  
  # FIRST TABLE - Combined stats
  stats_df <- calculate_combined_pitcher_stats(pitch_data, selected_pitcher, has_arm_angle)
  
  # Handle case where no stats are available
  if (nrow(stats_df) == 0) {
    return(grid.text("No pitch data available", gp = gpar(fontsize = 16, fontface = "bold")))
  }
  
  # Replace pitch codes with full names
  stats_df$`Pitch Type` <- pitch_names[stats_df$`Pitch Type`]
  # Drop unmapped pitch types (never occur in practice; NA name renders blank).
  stats_df <- stats_df[!is.na(stats_df$`Pitch Type`), ]

  # Convert pitch_type to factor with custom order
  stats_df$`Pitch Type` <- factor(stats_df$`Pitch Type`, levels = pitch_order)
  
  # Sort the dataframe by the factor levels
  stats_df <- stats_df[order(stats_df$`Pitch Type`), ]
  
  # Define headers for the combined table based on whether arm angle exists
  if (has_arm_angle) {
    combined_colnames <- c(
      "Pitch Type", "Count", "% Thrown", "Velocity", "Max Velo", "Spin Rate", "OTilt",
      "IVB", "HB", "RelZ", "RelX", "Ext", "Arm Angle",
      "VAA", "HAA",
      "Zone%", "CSW%", "Whiff%", "Chase%", "GB%"
    )
  } else {
    combined_colnames <- c(
      "Pitch Type", "Count", "% Thrown", "Velocity", "Max Velo", "Spin Rate", "OTilt",
      "IVB", "HB", "RelZ", "RelX", "Ext",
      "VAA", "HAA",
      "Zone%", "CSW%", "Whiff%", "Chase%", "GB%"
    )
  }
  
  # Set column names for the combined table
  names(stats_df) <- combined_colnames
  
  # SECOND TABLE - Platoon splits
  platoon_df <- calculate_platoon_stats(pitch_data, selected_pitcher)
  
  if (nrow(platoon_df) > 0) {
    # Replace pitch codes with full names
    platoon_df$`Pitch Type` <- pitch_names[platoon_df$`Pitch Type`]
    platoon_df <- platoon_df[!is.na(platoon_df$`Pitch Type`), ]

    # Convert pitch_type to factor with custom order
    platoon_df$`Pitch Type` <- factor(platoon_df$`Pitch Type`, levels = pitch_order)
    
    # Sort the dataframe by the factor levels  
    platoon_df <- platoon_df[order(platoon_df$`Pitch Type`), ]
    
    # Add duplicate pitch type column for LHH section
    platoon_df$pitch_type_lhh <- platoon_df$`Pitch Type`
    
    # Define headers for the platoon table with duplicate pitch type column
    platoon_colnames <- c(
      "Pitch Type", "Count", "% Thrown", "Zone%", "CSW%", "Whiff%", "Chase%", "GB%",
      "Pitch Type", "Count", "% Thrown", "Zone%", "CSW%", "Whiff%", "Chase%", "GB%"
    )
    
    # Reorder columns to include duplicate pitch type
    platoon_df <- platoon_df %>%
      select(`Pitch Type`, num_thrown_fmt_rhh, percent_thrown_rhh, iz_percent_rhh,
             csw_percent_rhh, swstr_percent_rhh, chase_percent_rhh, gb_percent_rhh,
             pitch_type_lhh, num_thrown_fmt_lhh, percent_thrown_lhh, iz_percent_lhh,
             csw_percent_lhh, swstr_percent_lhh, chase_percent_lhh, gb_percent_lhh)
    
    # Set column names
    names(platoon_df) <- platoon_colnames
  }
  
  # Create base table theme (tight horizontal padding so each column is only
  # as wide as its widest content)
  tt <- ttheme_minimal(
    core = list(
      fg_params = list(col = "black", fontsize = 9),
      bg_params = list(fill = "white"),
      padding = unit(c(2, 7), "mm")
    ),
    colhead = list(
      fg_params = list(
        col = "black",
        fontface = "bold",
        fontsize = 9,
        fontfamily = NULL
      ),
      bg_params = list(fill = "white"),
      padding = unit(c(2, 7), "mm")
    )
  )

  # Create the main stats table (column widths auto-size to fit content)
  tbl1 <- tableGrob(
    stats_df,
    rows = NULL,
    theme = tt
  )
  
  # Apply formatting to the main table
  tbl1 <- format_table(tbl1, stats_df, pitch_names)
  
  # Create platoon table if data exists
  if (nrow(platoon_df) > 0) {
    tbl2 <- tableGrob(
      platoon_df,
      rows = NULL,
      theme = tt
    )
    
    # Apply formatting to the platoon table
    tbl2 <- format_table(tbl2, platoon_df, pitch_names)
    
    # Add headers for vs RHH and vs LHH
    header_grob <- textGrob(
      c("vs RHH", "vs LHH"),
      x = c(0.3, 0.7),
      y = 0.5,
      gp = gpar(fontface = "bold", fontsize = 10)
    )
    
    # Combine both tables
    combined_tables <- arrangeGrob(
      tbl1,
      header_grob,
      tbl2,
      ncol = 1,
      heights = c(4, 0.3, 2)
    )
  } else {
    combined_tables <- tbl1
  }
  
  return(combined_tables)
}

# ---- Main Processing Function ----
generate_pitcher_reports <- function(input_file, output_dir,
                                     pitcher_filter = NULL,
                                     start_date = NULL,
                                     end_date = NULL) {
  # Read data (Supabase for known team codes, CSV otherwise)
  message("Reading pitch data from: ", input_file)
  pitch_data <- load_pitch_data(input_file)

  # Compute InZone from plate location and strike zone boundaries
  # (Description is already simplified by the Python downloader — no re-mapping needed)
  if (all(c("PlateX", "PlateZ", "SzTop", "SzBot") %in% names(pitch_data))) {
    pitch_data$InZone <- compute_in_zone(pitch_data$PlateX, pitch_data$PlateZ,
                                          pitch_data$SzTop, pitch_data$SzBot)
  }

  # Apply date filtering if specified
  if (!is.null(start_date) || !is.null(end_date)) {
    # Make sure Game Date is in date format
    pitch_data$Game_Date_dt <- as.Date(pitch_data$`Game Date`)
    
    # Filter by start date if provided
    if (!is.null(start_date)) {
      start_date_dt <- as.Date(start_date)
      pitch_data <- pitch_data %>% filter(Game_Date_dt >= start_date_dt)
      message("Filtered data to start from: ", start_date)
    }
    
    # Filter by end date if provided
    if (!is.null(end_date)) {
      end_date_dt <- as.Date(end_date)
      pitch_data <- pitch_data %>% filter(Game_Date_dt <= end_date_dt)
      message("Filtered data to end at: ", end_date)
    }
  }
  
  # Generate filename suffix based on date filters
  date_suffix <- ""
  if (!is.null(start_date) || !is.null(end_date)) {
    date_range <- paste0(
      ifelse(is.null(start_date), "Start", start_date),
      "_to_",
      ifelse(is.null(end_date), "End", end_date)
    )
    date_suffix <- paste0("_", date_range)
  }
  
  # Handle pitcher filtering
  if (!is.null(pitcher_filter)) {
    # If filtering for a specific pitcher, create a single report just for that pitcher
    message("Creating report for specific pitcher: ", pitcher_filter)
    
    # Filter for a single pitcher
    pitcher_data <- pitch_data %>% filter(Pitcher == pitcher_filter)
    
    if (nrow(pitcher_data) == 0) {
      message("No data found for pitcher: ", pitcher_filter, " in the specified date range")
      return(NULL)
    }
    
    # Get the team for the pitcher
    current_team <- unique(pitcher_data$PTeam)[1]
    
    # Create a cleaner version of the pitcher name for the filename
    clean_pitcher_name <- gsub(", ", "_", pitcher_filter) %>% 
      gsub(" ", "_", .) %>%
      gsub("[^A-Za-z0-9_]", "", .)
    
    # Create pitcher-specific PDF with date range if applicable
    pdf_filename <- paste0(output_dir, clean_pitcher_name, date_suffix, "_Pitcher_Report.pdf")
    pdf(pdf_filename, width = 15, height = 18)
    
    # Filter for movement data
    pitch_data_filtered <- pitcher_data %>%
      drop_na(xHorzBrk, xIndVrtBrk)
    
    if (nrow(pitch_data_filtered) > 0) {
      # Create the pitch movement plot (all data combined)
      pitch_plot <- create_pitch_plot(pitch_data_filtered, pitcher_filter)
      
      # Create the stats tables (all data combined)
      table_plot <- create_pitcher_tables(pitcher_data, pitcher_filter)
      
      # Combine plot and table
      combined_plot <- plot_grid(
        pitch_plot,
        table_plot,
        ncol = 1,
        rel_heights = c(1.2, 1)
      )
      
      # Print the plot to the current PDF page
      print(combined_plot)
      message(paste("Created plot for", pitcher_filter))
    } else {
      message(paste("Skipping", pitcher_filter, "- no valid movement data"))
    }
    
    # Close the PDF
    dev.off()
    message(paste("Pitcher report for", pitcher_filter, "saved to", pdf_filename))
    
  } else {
    # Original functionality - create team-based reports
    # Get list of all unique teams
    all_teams <- unique(pitch_data$PTeam)
    message("Found ", length(all_teams), " teams in the dataset")
    
    # Process each team separately
    for (current_team in all_teams) {
      # Create team-specific PDF with date range if applicable
      pdf_filename <- paste0(output_dir, current_team, date_suffix, "_Pitcher_Reports.pdf")
      message("Creating report for team: ", current_team)
      pdf(pdf_filename, width = 15, height = 18)
      
      # Get pitchers for this team
      all_pitchers <- pitch_data %>%
        filter(PTeam == current_team) %>%
        pull(Pitcher) %>%
        unique() %>%
        sort()
      
      message("Processing ", length(all_pitchers), " pitchers for ", current_team)
      
      # Loop through each pitcher
      for (selected_pitcher in all_pitchers) {
        # Get all data for this pitcher
        pitcher_data <- pitch_data %>%
          filter(Pitcher == selected_pitcher)
        
        # Skip pitchers with no valid movement data
        pitch_data_filtered <- pitcher_data %>%
          drop_na(xHorzBrk, xIndVrtBrk)
        
        if (nrow(pitch_data_filtered) == 0) {
          message(paste("Skipping", selected_pitcher, "- no valid movement data"))
          next
        }
        
        # Create the pitch movement plot (all data combined)
        pitch_plot <- create_pitch_plot(pitch_data_filtered, selected_pitcher)
        
        # Create the stats tables (all data combined)
        table_plot <- create_pitcher_tables(pitcher_data, selected_pitcher)
        
        # Combine plot and table
        combined_plot <- plot_grid(
          pitch_plot,
          table_plot,
          ncol = 1,
          rel_heights = c(1.2, 1)
        )
        
        # Print the plot to the current PDF page
        print(combined_plot)
        message(paste("Created plot for", selected_pitcher))
      }
      
      # Close the PDF device for this team
      dev.off()
      message(paste("Pitcher report for team", current_team, "saved to", pdf_filename))
    }
    
    message("All team pitcher reports have been created")
  }
}

# ---- Execute Main Function ----
# Pass the optional filter parameters to the function
generate_pitcher_reports(
  input_file_path, 
  output_directory,
  pitcher_filter = selected_pitcher_filter,
  start_date = start_date_filter,
  end_date = end_date_filter
)