# ---- Configuration ----
input_file_path <- "FCL"  # Team code (e.g., "PIT", "WSH") or full path
output_directory <- "/Users/wallyhuron/Downloads/"

# ---- Optional Filtering Parameters ----
# Set these to NULL to disable filtering
selected_pitcher_filter <- "Pilkington, Konnor"  # Example format: "Bieber, Shane" 
start_date_filter <- "2026-02-07"        # Example format: "2025-04-01"
end_date_filter <- "2026-11-28"         # Example format: "2025-04-20"

# ---- Required Libraries ----
library(tidyverse)
library(patchwork)
library(gridExtra)
library(gtable)
library(grid)
library(cowplot)

# Source shared utilities (pitch_names, pitch_colors, pitch_order, compute_in_zone, avg_tilt_clock, col_has_data)
source("/Users/wallyhuron/Huronalytics/R-scripts/pitcher_report_utils.R")

# Allow command-line overrides: Rscript OnePitcher.R "/path/to/file.csv" "2026-04-08" "2026-04-08" "Penrod, Zach"
cli_args <- commandArgs(trailingOnly = TRUE)
if (length(cli_args) >= 1) input_file_path <- cli_args[1]
if (length(cli_args) >= 2) start_date_filter <- cli_args[2]
if (length(cli_args) >= 3) end_date_filter <- cli_args[3]
if (length(cli_args) >= 4) selected_pitcher_filter <- cli_args[4]

# Resolve team code to full path (e.g., "PIT" -> "/Users/wallyhuron/Downloads/NL 2026 - PIT.csv")
input_file_path <- resolve_team_path(input_file_path)

# ---- Data Processing Functions ----

# Function to calculate pitch stats for first table
calculate_pitcher_stats <- function(data, pitcher_name, has_arm_angle = FALSE) {
  pitcher_data <- data %>%
    filter(Pitcher == pitcher_name)
  
  total_pitches <- nrow(pitcher_data)
  
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
    )
  
  # Select columns based on whether arm angle data exists
  if (has_arm_angle) {
    result %>%
      select(
        `Pitch Type`, num_thrown, percent_thrown, avg_velo, max_velo, avg_spin, avg_tilt,
        avg_ivb, avg_hb, avg_height, avg_side, avg_extension, avg_arm_angle, avg_vaa, avg_haa
      )
  } else {
    result %>%
      select(
        `Pitch Type`, num_thrown, percent_thrown, avg_velo, max_velo, avg_spin, avg_tilt,
        avg_ivb, avg_hb, avg_height, avg_side, avg_extension, avg_vaa, avg_haa
      )
  }
}

# Function to calculate stats for second table
calculate_pitcher_stats_table2 <- function(data, pitcher_name) {
  pitcher_data <- data %>%
    filter(Pitcher == pitcher_name)

  total_pitches <- nrow(pitcher_data)
  has_bb_type <- "BBType" %in% names(data)

  # Define pitch outcome event categories (simplified descriptions)
  swing_events <- c(
    "Swinging Strike", "Foul", "In Play"
  )

  csw_events <- c(
    "Called Strike", "Swinging Strike"
  )

  swstr_events <- c(
    "Swinging Strike"
  )

  in_play_events <- c("In Play")

  pitcher_data %>%
    group_by(`Pitch Type`) %>%
    summarize(
      num_thrown = sprintf("%.0f", n()),
      percent_thrown = sprintf("%.1f%%", n() / total_pitches * 100),
      # IZ% using Zone column (zones 1-9 are in zone)
      iz_percent = sprintf(
        "%.1f%%",
        sum(InZone == "Yes", na.rm = TRUE) / n() * 100
      ),
      swing_percent = sprintf("%.1f%%", sum(Description %in% swing_events, na.rm = TRUE) / n() * 100),
      csw_percent = sprintf("%.1f%%", sum(Description %in% csw_events, na.rm = TRUE) / n() * 100),
      swstr_percent = {
        total_swings <- sum(Description %in% swing_events, na.rm = TRUE)
        if (total_swings > 0) {
          sprintf("%.1f%%", sum(Description %in% swstr_events, na.rm = TRUE) / total_swings * 100)
        } else {
          "---"
        }
      },
      # Chase% = swings on pitches outside zone / pitches outside zone
      chase_percent = {
        ooz_pitches <- sum(InZone == "No", na.rm = TRUE)
        if (ooz_pitches > 0) {
          sprintf("%.1f%%", sum(Description %in% swing_events & (InZone == "No"), na.rm = TRUE) / ooz_pitches * 100)
        } else {
          "---"
        }
      },
      gb_percent = {
        if (has_bb_type) {
          total_bip <- sum(Description %in% in_play_events & !grepl("^bunt", BBType), na.rm = TRUE)
          if (total_bip > 0) {
            # Gate on the in-play description too, matching Season.R and the
            # total_bip denominator — otherwise a ground_ball tagged on a non
            # "In Play" row (e.g. a foul grounder) inflates GB% and can exceed 100%.
            n_gb <- sum(Description %in% in_play_events & BBType == "ground_ball", na.rm = TRUE)
            sprintf("%.1f%%", n_gb / total_bip * 100)
          } else {
            "---"
          }
        } else {
          "---"
        }
      },
    ) %>%
    select(
      `Pitch Type`, num_thrown, percent_thrown, iz_percent, swing_percent,
      csw_percent, swstr_percent, chase_percent, gb_percent
    )
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
    pitch_full <- stats_df$`Pitch Type`[i]
    # Find the first matching pitch code
    pitch_code <- names(which(pitch_names == pitch_full))[1]
    
    # Only proceed if we found a matching pitch code
    if (!is.na(pitch_code) && pitch_code %in% names(pitch_colors)) {
      color_info <- pitch_colors[[pitch_code]]
      tbl$grobs[[bg_indices[i]]]$gp$fill <- color_info$fill
      tbl$grobs[[fg_indices[i]]]$gp$col <- color_info$text
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
    tbl$grobs[[which(grepl("colhead", tbl$layout$name))[i]]]$gp <- 
      gpar(col = "black", fontface = "bold", fontsize = 10)
  }
  
  return(tbl)
}

# Function to create pitch movement plot
create_pitch_plot <- function(pitch_data_filtered, pitcher_name, game_date = NULL) {
  # Format pitcher name for title
  pitcher_name <- str_replace(pitcher_name, "(.*), (.*)", "\\2 \\1")
  
  # Create the title with explicit date formatting
  if (is.null(game_date)) {
    title_text <- paste(pitcher_name, "Pitch Movement")
  } else {
    # Force the game_date to be treated as a string
    title_text <- paste0(pitcher_name, " Pitch Movement ", as.character(game_date))
  }
  
  ggplot(
    pitch_data_filtered, 
    aes(x = xHorzBrk, y = xIndVrtBrk, color = `Pitch Type`, fill = `Pitch Type`)
  ) +
    geom_hline(yintercept = 0, color = "black", linetype = "dashed", linewidth = 0.5) +  
    geom_vline(xintercept = 0, color = "black", linetype = "dashed", linewidth = 0.5) +  
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
}

# Function to create pitcher stats tables
create_pitcher_tables <- function(pitch_data, selected_pitcher, game_date = NULL) {
  # Filter by date if provided
  if (!is.null(game_date)) {
    pitch_data <- pitch_data %>% 
      filter(`Game Date` == game_date)
  }
  
  # Check if Arm Angle column exists and has data for this pitcher
  has_arm_angle <- "ArmAngle" %in% names(pitch_data) && 
    any(!is.na(pitch_data$ArmAngle[pitch_data$Pitcher == selected_pitcher]))
  
  stats_df <- calculate_pitcher_stats(pitch_data, selected_pitcher, has_arm_angle)
  
  # Handle case where no stats are available
  if (nrow(stats_df) == 0) {
    return(grid.text("No pitch data available", gp = gpar(fontsize = 16, fontface = "bold")))
  }
  
  # Replace pitch codes with full names
  stats_df$`Pitch Type` <- pitch_names[stats_df$`Pitch Type`]
  # Drop unmapped pitch types (never occur in practice; an NA name would render
  # as a blank/NA row and sort unpredictably).
  stats_df <- stats_df[!is.na(stats_df$`Pitch Type`), ]

  # Convert Pitch Type to factor (levels act as the usage tie-break order)
  stats_df$`Pitch Type` <- factor(stats_df$`Pitch Type`, levels = pitch_order)

  # Sort by usage (descending); exact ties fall back to pitch_order
  stats_df <- stats_df[order(-as.numeric(stats_df$num_thrown), stats_df$`Pitch Type`), ]
  
  # FIRST TABLE - Use stats_df directly
  stats_df_table1 <- stats_df
  
  # Define headers for first table based on whether arm angle exists
  if (has_arm_angle) {
    table1_colnames <- c(
      "Pitch Type", "Count", "% Thrown", "Velocity", "Max Velo", "Spin Rate", "OTilt",
      "IVB", "HB", "RelZ", "RelX", "Ext", "Arm Angle", "VAA", "HAA"
    )
  } else {
    table1_colnames <- c(
      "Pitch Type", "Count", "% Thrown", "Velocity", "Max Velo", "Spin Rate", "OTilt",
      "IVB", "HB", "RelZ", "RelX", "Ext", "VAA", "HAA"
    )
  }
  
  # Set column names for first table
  names(stats_df_table1) <- table1_colnames
  
  # SECOND TABLE - Calculate additional stats
  stats_df_table2 <- calculate_pitcher_stats_table2(pitch_data, selected_pitcher)
  stats_df_table2$`Pitch Type` <- pitch_names[stats_df_table2$`Pitch Type`]
  stats_df_table2 <- stats_df_table2[!is.na(stats_df_table2$`Pitch Type`), ]
  stats_df_table2$`Pitch Type` <- factor(stats_df_table2$`Pitch Type`, levels = pitch_order)
  stats_df_table2 <- stats_df_table2[order(-as.numeric(stats_df_table2$num_thrown),
                                           stats_df_table2$`Pitch Type`), ]
  
  # Define headers for second table (removed BBE and Exit Velo)
  table2_colnames <- c(
    "Pitch Type", "Count", "% Thrown", "Zone%", "Swing%",
    "CSW%", "Whiff%", "Chase%", "GB%"
  )
  
  # Set column names for second table
  names(stats_df_table2) <- table2_colnames
  
  # Create base table theme with larger font; tight horizontal padding so each
  # column is only as wide as its widest content
  tt <- ttheme_minimal(
    core = list(
      fg_params = list(col = "black", fontsize = 16),
      bg_params = list(fill = "white"),
      padding = unit(c(2, 8), "mm")
    ),
    colhead = list(
      fg_params = list(
        col = "black",
        fontface = "bold",
        fontsize = 16,
        fontfamily = NULL
      ),
      bg_params = list(fill = "white"),
      padding = unit(c(2, 8), "mm")
    )
  )

  # Create both tables (column widths auto-size to fit content)
  tbl1 <- tableGrob(
    stats_df_table1,
    rows = NULL,
    theme = tt
  )

  tbl2 <- tableGrob(
    stats_df_table2,
    rows = NULL,
    theme = tt
  )
  
  # Apply formatting to both tables
  tbl1 <- format_table(tbl1, stats_df_table1, pitch_names)
  tbl2 <- format_table(tbl2, stats_df_table2, pitch_names)
  
  # Combine both tables with some spacing
  arrangeGrob(
    tbl1, 
    tbl2, 
    ncol = 1, 
    heights = c(1, 1), 
    padding = unit(1.5, "cm")
  )
}

# ---- Main Processing Function ----
generate_pitcher_reports <- function(input_file, output_dir, 
                                     pitcher_filter = NULL, 
                                     start_date = NULL, 
                                     end_date = NULL) {
  # Read data (Supabase for known team codes, CSV otherwise). OTilt stays
  # character to prevent time parsing — handled inside load_pitch_data().
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
    
    # Get unique game dates for this pitcher
    game_dates <- unique(pitcher_data$`Game Date`)
    
    # If there's only one date, process as before
    if (length(game_dates) == 1) {
      # Filter for movement data
      pitch_data_filtered <- pitcher_data %>%
        drop_na(xHorzBrk, xIndVrtBrk)
      
      if (nrow(pitch_data_filtered) > 0) {
        # Create the pitch movement plot
        pitch_plot <- create_pitch_plot(pitch_data_filtered, pitcher_filter)
        
        # Create the stats tables
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
    } else {
      # If there are multiple dates, create a separate page for each date
      message(paste("Found", length(game_dates), "different game dates for", pitcher_filter))
      
      # Sort game dates chronologically (earliest to latest)
      game_dates <- sort(game_dates)
      
      for (game_date in game_dates) {
        # Filter data for this specific date
        date_data <- pitcher_data %>% 
          filter(`Game Date` == game_date)
        
        # Filter for movement data
        pitch_data_filtered <- date_data %>%
          drop_na(xHorzBrk, xIndVrtBrk)
        
        if (nrow(pitch_data_filtered) > 0) {
          # Format date as string (YYYY-MM-DD)
          date_string <- format(as.Date(game_date), "%Y-%m-%d")
          
          # Create the pitch movement plot with date in title
          pitch_plot <- create_pitch_plot(pitch_data_filtered, pitcher_filter, date_string)
          
          # Create the stats tables for this date
          table_plot <- create_pitcher_tables(date_data, pitcher_filter)
          
          # Combine plot and table
          combined_plot <- plot_grid(
            pitch_plot,
            table_plot,
            ncol = 1,
            rel_heights = c(1.2, 1)
          )
          
          # Print the plot to the current PDF page
          print(combined_plot)
          message(paste("Created plot for", pitcher_filter, "on", game_date))
        } else {
          message(paste("Skipping", pitcher_filter, "on", game_date, "- no valid movement data"))
        }
      }
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
        unique() %>% sort()
      
      message("Processing ", length(all_pitchers), " pitchers for ", current_team)
      
      # Loop through each pitcher
      for (selected_pitcher in all_pitchers) {
        # Get all data for this pitcher
        pitcher_data <- pitch_data %>%
          filter(Pitcher == selected_pitcher)
        
        # Get unique game dates for this pitcher
        game_dates <- unique(pitcher_data$`Game Date`)
        
        # If there's only one date, process as before
        if (length(game_dates) == 1) {
          # Skip pitchers with no valid movement data
          pitch_data_filtered <- pitcher_data %>%
            drop_na(xHorzBrk, xIndVrtBrk)
          
          if (nrow(pitch_data_filtered) == 0) {
            message(paste("Skipping", selected_pitcher, "- no valid movement data"))
            next
          }
          
          # Create the pitch movement plot
          pitch_plot <- create_pitch_plot(pitch_data_filtered, selected_pitcher)
          
          # Create the stats tables
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
        } else {
          # If there are multiple dates, create a separate page for each date
          message(paste("Found", length(game_dates), "different game dates for", selected_pitcher))
          
          # Sort game dates chronologically (earliest to latest)
          game_dates <- sort(game_dates)
          
          for (game_date in game_dates) {
            # Filter data for this specific date
            date_data <- pitcher_data %>% 
              filter(`Game Date` == game_date)
            
            # Filter for movement data
            pitch_data_filtered <- date_data %>%
              drop_na(xHorzBrk, xIndVrtBrk)
            
            if (nrow(pitch_data_filtered) == 0) {
              message(paste("Skipping", selected_pitcher, "on", game_date, "- no valid movement data"))
              next
            }
            
            # Format date as string (YYYY-MM-DD)
            date_string <- format(as.Date(game_date), "%Y-%m-%d")
            
            # Create the pitch movement plot with date in title
            pitch_plot <- create_pitch_plot(pitch_data_filtered, selected_pitcher, date_string)
            
            # Create the stats tables for this date
            table_plot <- create_pitcher_tables(date_data, selected_pitcher)
            
            # Combine plot and table
            combined_plot <- plot_grid(
              pitch_plot,
              table_plot,
              ncol = 1,
              rel_heights = c(1.2, 1)
            )
            
            # Print the plot to the current PDF page
            print(combined_plot)
            message(paste("Created plot for", selected_pitcher, "on", game_date))
          }
        }
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