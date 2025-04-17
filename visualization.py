import os
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from scipy.signal import find_peaks
from datetime import datetime
import json
import shutil
import time
import re
import uuid
import sys
import traceback
from utils import wavelength_to_rgb

#=============================================================================
# VISUALIZATION CONFIGURATION PARAMETERS
#=============================================================================

# Visualization Enhancement Settings
CONTRAST_FACTOR = 1                # Contrast enhancement factor (higher = more contrast)
SNAKE_PATTERN = True               # Whether to use snake pattern for visualization

# Visualization Appearance Settings
MARKER_SIZE_MIN = 2                # Minimum marker size
MARKER_SIZE_RANGE = 8              # Range of marker sizes (added to minimum)
FIGURE_HEIGHT = 950                # Height of figure in pixels
TEMPLATE = 'plotly_dark'           # Plotly template ('plotly', 'plotly_white', 'plotly_dark', etc.)
SCENE_ASPECT_RATIO = dict(x=1, y=2, z=1)  # Aspect ratio for 3D scene

# Normalization Visualization Settings
NORMALIZED_COLORSCALE = 'RdBu_r'   # Colorscale for normalized data (RdBu_r: blue=low, white=100%, red=high)
NORMALIZED_RANGE = [0, 200]        # Range for normalized data (0-200% for percentage transmission)
USE_NORMALIZED_COLORSCALE = False   # Whether to use special colorscale for normalized data

# Intensity Threshold Settings
DEFAULT_INTENSITY_THRESHOLD = 0    # Default intensity threshold in percentage (0-100)
INTENSITY_THRESHOLD_STEPS = [      # Intensity threshold steps for the slider in percentage
    0, 5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 95
]

# Wavelength Sampling Settings
MAX_WAVELENGTH_POINTS = 30        # Maximum number of wavelength points to plot (for performance)
WAVELENGTH_SLICE_FACTOR = 2        # Factor to make wavelength slices narrower (higher = narrower)
DISABLE_ANIMATION = False          # Whether to disable animation for better performance

# Wavelength Filter Ranges (in nm)
WAVELENGTH_FILTERS = [
    {"name": "All Wavelengths", "range": None},
    {"name": "UV-Violet (< 400 nm)", "range": (0, 400)},
    {"name": "Violet (400-450 nm)", "range": (400, 450)},
    {"name": "Blue (450-490 nm)", "range": (450, 490)},
    {"name": "Cyan (490-520 nm)", "range": (490, 520)},
    {"name": "Green (520-560 nm)", "range": (520, 560)},
    {"name": "Yellow-Green (560-580 nm)", "range": (560, 580)},
    {"name": "Yellow (580-600 nm)", "range": (580, 600)},
    {"name": "Orange (600-650 nm)", "range": (600, 650)},
    {"name": "Red (650-750 nm)", "range": (650, 750)},
    {"name": "NIR (> 750 nm)", "range": (750, 2000)}
]

# Output Settings
OUTPUT_DIRECTORY = "output"                                                        # Directory for saving output files
OUTPUT_HTML_FILE = os.path.join(OUTPUT_DIRECTORY, "interactive_spectral_visualization.html")  # Output HTML file name

# 2D Visualization Settings
COLORSCALE = 'Greys_r'             # Colorscale for heatmap ('Greys_r' is inverted grayscale - higher intensity = brighter)
LOG_SCALE = True                   # Whether to use log scale for intensity values
WAVELENGTH_STEP = 5                # Step size for wavelength slider (smaller = smoother scrolling but more frames)
GLOBAL_INTENSITY_SCALE = True      # Whether to use the same intensity scale for all wavelengths
DARK_MODE = True                   # Whether to use dark mode for the visualization

# function to handle dynamic output paths
def get_output_path(scan_dir=None, filename="visualization.html", prefix=""):
    """
    Get appropriate output path for visualization files
    
    Args:
        scan_dir: Scan directory (if None, uses default output directory)
        filename: Base filename
        prefix: Optional prefix for the filename
        
    Returns:
        Full output path
    """
    if scan_dir is not None:
        # Use scan directory if provided
        full_filename = f"{prefix}{filename}" if prefix else filename
        return os.path.join(scan_dir, full_filename)
    else:
        # Fall back to default output directory
        os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
        full_filename = f"{prefix}{filename}" if prefix else filename
        return os.path.join(OUTPUT_DIRECTORY, full_filename)

#=============================================================================
# 3D VISUALIZATION FUNCTIONS
#=============================================================================

def create_interactive_spectral_vis(wavelengths, counts_cube, grid_width, grid_height, 
                                   contrast_factor=CONTRAST_FACTOR, snake_pattern=False,
                                   is_normalized=False, normalization_type=None,
                                   output_html=None, scan_dir=None):
    """
    Create an interactive 3D visualization of spectral data using Plotly.
    Modified to handle missing data points properly.
    """
    try:
        import plotly.graph_objects as go
        import plotly.express as px
        print("Successfully imported Plotly for interactive visualization")
    except ImportError:
        print("Error: Plotly is not installed. Please install with 'pip install plotly'")
        print("Falling back to matplotlib visualization")
        return
    
    print("Creating interactive 3D spectral visualization with Plotly...")
    
    # Calculate the maximum intensity for normalization and thresholding
    global_max_intensity = np.nanmax(counts_cube)  # Use nanmax to ignore NaN values
    print(f"Maximum global intensity: {global_max_intensity}")
    
    # For normalized data, handle intensity differently
    if is_normalized and normalization_type == 'percentage':
        reference_value = 100
    elif is_normalized and normalization_type == 'ratio':
        reference_value = 1.0
    else:
        reference_value = None
    
    # Sample wavelengths for better performance
    if len(wavelengths) > MAX_WAVELENGTH_POINTS:
        sample_rate = len(wavelengths) // MAX_WAVELENGTH_POINTS * WAVELENGTH_SLICE_FACTOR
        wavelength_indices = range(0, len(wavelengths), sample_rate)
        sampled_wavelengths = wavelengths[wavelength_indices]
    else:
        sample_rate = WAVELENGTH_SLICE_FACTOR
        wavelength_indices = range(0, len(wavelengths), sample_rate)
        sampled_wavelengths = wavelengths[wavelength_indices]
    
    # For efficient filtering, we'll collect all data points
    all_x = []                  # X position
    all_y = []                  # Wavelength
    all_z = []                  # Y position
    all_wavelengths = []        # Actual wavelength (for filtering)
    all_intensity = []          # Normalized intensity values (for filtering)
    all_global_intensity_pct = [] # Global intensity percentage
    all_point_size = []         # Size for plotly (depends on intensity)
    all_colors = []             # RGBA color values
    all_position_ids = []       # Position IDs for identifying points
    
    print(f"Processing data for grid dimensions: {grid_width}x{grid_height}...")
    
    # Process each position in the grid
    for y_idx in range(grid_height):
        for x_idx in range(grid_width):
            # Calculate linear index based on grid position
            # This assumes data is stored in row-major order (y_idx * width + x_idx)
            linear_idx = y_idx * grid_width + x_idx
            
            # Skip if linear_idx is out of bounds
            if linear_idx >= counts_cube.shape[0]:
                print(f"Warning: Linear index {linear_idx} exceeds data cube size {counts_cube.shape[0]}")
                continue
                
            # Set grid x and z positions (z is inverted to match common grid visualization)
            grid_x = x_idx
            grid_z = grid_height - 1 - y_idx
            
            # Position ID for identifying the spectrum
            position_id = f"({grid_x},{grid_z})"
            
            if linear_idx % 10 == 0:
                print(f"Processing grid position {linear_idx+1}/{grid_width*grid_height} at {position_id}...")
            
            # Sample intensities for this spectrum
            sampled_counts = counts_cube[linear_idx][wavelength_indices]
            
            # Skip points with all NaN values (completely missing data)
            if np.all(np.isnan(sampled_counts)):
                print(f"Skipping position {position_id} - missing data")
                continue
            
            # Handle normalization differently based on type
            if is_normalized:
                # For normalized data, show deviation from reference value (100% or 1.0)
                if normalization_type == 'percentage':
                    deviation_values = sampled_counts - 100
                    size_intensity = np.abs(sampled_counts - 100) / 100
                else:
                    deviation_values = sampled_counts - 1.0
                    size_intensity = np.abs(sampled_counts - 1.0)
                
                # Cap size intensity to a reasonable range
                size_intensity = np.minimum(size_intensity, 2.0)
                
                # For color intensity in normalized data, use the actual normalized values
                color_intensity = sampled_counts
            else:
                # For unnormalized data, use standard approach
                # Normalize intensities within this spectrum
                local_max = np.nanmax(sampled_counts)  # Use nanmax to ignore NaN values
                if local_max > 0:
                    normalized_local = sampled_counts / local_max
                    # Replace NaNs with zeros
                    normalized_local = np.nan_to_num(normalized_local, nan=0.0)
                else:
                    normalized_local = np.zeros_like(sampled_counts)
                
                # Apply contrast enhancement
                size_intensity = normalized_local ** contrast_factor
                color_intensity = normalized_local
                deviation_values = None
            
            # Calculate global intensity percentages
            if global_max_intensity > 0:
                global_intensity_pct = sampled_counts / global_max_intensity * 100
                # Replace NaNs with zeros
                global_intensity_pct = np.nan_to_num(global_intensity_pct, nan=0.0)
            else:
                global_intensity_pct = np.zeros_like(sampled_counts)
            
            # Skip the NaN values when creating arrays
            valid_mask = ~np.isnan(sampled_counts)
            valid_wavelengths = sampled_wavelengths[valid_mask]
            valid_size_intensity = size_intensity[valid_mask]
            valid_color_intensity = color_intensity[valid_mask]
            valid_global_pct = global_intensity_pct[valid_mask]
            
            if len(valid_wavelengths) == 0:
                continue  # Skip if no valid data points
            
            # Create arrays of x and z coordinates
            x_coords = np.full(len(valid_wavelengths), grid_x)
            z_coords = np.full(len(valid_wavelengths), grid_z)
            position_ids = np.full(len(valid_wavelengths), position_id, dtype=object)
            
            # Make sizes proportional to intensity
            sizes = MARKER_SIZE_MIN + valid_size_intensity * MARKER_SIZE_RANGE
            
            # Create RGBA colors - different approach for normalized vs non-normalized
            colors = []
            
            if is_normalized and USE_NORMALIZED_COLORSCALE:
                # Special colormap for normalized data
                try:
                    import matplotlib.pyplot as plt
                    from matplotlib import cm
                    
                    # Get colormap
                    if normalization_type == 'percentage':
                        cmap = plt.get_cmap('RdBu_r')
                        norm_values = np.clip(valid_color_intensity / 100, 0, 2)
                    else:
                        cmap = plt.get_cmap('RdBu_r')
                        norm_values = np.clip(valid_color_intensity, 0, 2)
                    
                    # Create RGBA colors from colormap
                    for value, intensity in zip(norm_values, valid_size_intensity):
                        rgba = cmap(value)
                        alpha = min(1.0, max(0.2, float(intensity)))
                        r_int = int(rgba[0] * 255)
                        g_int = int(rgba[1] * 255)
                        b_int = int(rgba[2] * 255)
                        color = f'rgba({r_int},{g_int},{b_int},{alpha})'
                        colors.append(color)
                except Exception as e:
                    print(f"Error creating normalized colormap: {e}")
                    # Fall back to standard wavelength coloring
                    for wl, intensity in zip(valid_wavelengths, valid_size_intensity):
                        r, g, b = wavelength_to_rgb(wl)
                        darkness_factor = max(0.1, intensity)
                        r = r * darkness_factor
                        g = g * darkness_factor
                        b = b * darkness_factor
                        alpha = min(1.0, max(0.1, float(intensity)))
                        r_int = int(r * 255)
                        g_int = int(g * 255)
                        b_int = int(b * 255)
                        color = f'rgba({r_int},{g_int},{b_int},{alpha})'
                        colors.append(color)
            else:
                # Standard wavelength-based coloring
                for wl, intensity in zip(valid_wavelengths, valid_size_intensity):
                    r, g, b = wavelength_to_rgb(wl)
                    darkness_factor = max(0.1, intensity ** 1.5)
                    r = r * darkness_factor
                    g = g * darkness_factor
                    b = b * darkness_factor
                    r_int = int(r * 255)
                    g_int = int(g * 255)
                    b_int = int(b * 255)
                    alpha = min(1.0, max(0.1, float(intensity)))
                    color = f'rgba({r_int},{g_int},{b_int},{alpha})'
                    colors.append(color)
            
            # Add data points to main arrays
            all_x.extend(x_coords)
            all_y.extend(valid_wavelengths)
            all_z.extend(z_coords)
            all_wavelengths.extend(valid_wavelengths)
            all_intensity.extend(valid_color_intensity)
            all_global_intensity_pct.extend(valid_global_pct)
            all_point_size.extend(sizes)
            all_colors.extend(colors)
            all_position_ids.extend(position_ids)
    
    # Create a DataFrame for all the data points
    df = pd.DataFrame({
        'x': all_x,
        'y': all_y,  # Wavelength as y-coordinate
        'z': all_z, 
        'wavelength': all_wavelengths,
        'intensity': all_intensity,
        'global_intensity_pct': all_global_intensity_pct,
        'size': all_point_size,
        'color': all_colors,
        'position': all_position_ids,
        'wavelength_range': pd.cut(
            all_wavelengths,
            bins=[0, 400, 490, 570, 750, float('inf')],
            labels=['<400nm', '400-490nm', '490-570nm', '570-750nm', '>750nm']
        )
    })
    
    print(f"Created DataFrame with {len(df)} data points")
    
    # Apply initial intensity threshold based on percentage
    df_filtered = df[df['global_intensity_pct'] >= DEFAULT_INTENSITY_THRESHOLD]
    print(f"After filtering: {len(df_filtered)} data points shown (out of {len(df)} total)")

    
    # Create the figure
    fig = go.Figure()
    
    # Add the main scatter3d trace with all points
    # Generate hover text appropriately based on normalization
    if is_normalized:
        if normalization_type == 'percentage':
            # For percentage normalization
            hover_text = [
                f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                f"Transmission: {row['intensity']:.1f}%<br>"
                f"Relative to background: {row['intensity'] - 100:.1f}%"
                for _, row in df_filtered.iterrows()
            ]
        else:
            # For ratio normalization
            hover_text = [
                f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                f"Transmission ratio: {row['intensity']:.3f}<br>"
                f"Relative to background: {row['intensity'] - 1.0:.3f}"
                for _, row in df_filtered.iterrows()
            ]
    else:
        # For standard non-normalized data
        hover_text = [
            f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
            f"Intensity: {row['intensity']:.2f}<br>"
            f"Global %: {row['global_intensity_pct']:.1f}%"
            for _, row in df_filtered.iterrows()
        ]
    
    # Add the main scatter3d trace with all points
    fig.add_trace(go.Scatter3d(
        x=df_filtered['x'],
        y=df_filtered['y'],  # Wavelength as y-coordinate
        z=df_filtered['z'],
        mode='markers',
        marker=dict(
            size=df_filtered['size'],
            color=df_filtered['color'].tolist(),
            line=dict(width=0)
        ),
        text=hover_text,
        hovertemplate="%{text}<br>",
        name='Spectral Data'
    ))
    
    # Create buttons for wavelength filters with proper handling of text generation
    wavelength_buttons = []
    
    # Add "All Wavelengths" button
    # Generate appropriate hover text based on normalization
    if is_normalized:
        if normalization_type == 'percentage':
            all_wavelengths_text = [
                f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                f"Transmission: {row['intensity']:.1f}%<br>"
                f"Relative to background: {row['intensity'] - 100:.1f}%"
                for _, row in df_filtered.iterrows()
            ]
        else:
            all_wavelengths_text = [
                f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                f"Transmission ratio: {row['intensity']:.3f}<br>"
                f"Relative to background: {row['intensity'] - 1.0:.3f}"
                for _, row in df_filtered.iterrows()
            ]
    else:
        all_wavelengths_text = [
            f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
            f"Intensity: {row['intensity']:.2f}<br>"
            f"Global %: {row['global_intensity_pct']:.1f}%"
            for _, row in df_filtered.iterrows()
        ]
    
    wavelength_buttons.append(dict(
        label="All Wavelengths",
        method="update",
        args=[{
            "x": [df_filtered['x'].tolist()], 
            "y": [df_filtered['y'].tolist()], 
            "z": [df_filtered['z'].tolist()],
            "marker.size": [df_filtered['size'].tolist()],
            "marker.color": [df_filtered['color'].tolist()],
            "text": [all_wavelengths_text]
        }]
    ))
    
    # Add buttons for specific wavelength ranges
    for filter_item in WAVELENGTH_FILTERS[1:]:  # Skip "All Wavelengths" as we already added it
        filter_name = filter_item["name"]
        filter_range = filter_item["range"]
        
        # Make button labels more compact
        label = filter_name
        if "(" in label:
            # Extract just the range part for more compact labels
            label = label.split("(")[1].split(")")[0]
        
        if filter_range:
            min_wl, max_wl = filter_range
            
            # Adjust the filter condition based on range type
            if min_wl == 0:  # For "UV-Violet (< 400 nm)"
                wl_filtered = df_filtered[df_filtered['wavelength'] < max_wl]
            elif max_wl > 1000:  # For "NIR (> 750 nm)"
                wl_filtered = df_filtered[df_filtered['wavelength'] > min_wl]
            else:
                # Normal range
                wl_filtered = df_filtered[(df_filtered['wavelength'] >= min_wl) & (df_filtered['wavelength'] <= max_wl)]
            
            # Generate appropriate hover text based on normalization
            if is_normalized:
                if normalization_type == 'percentage':
                    wl_text = [
                        f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                        f"Transmission: {row['intensity']:.1f}%<br>"
                        f"Relative to background: {row['intensity'] - 100:.1f}%"
                        for _, row in wl_filtered.iterrows()
                    ]
                else:
                    wl_text = [
                        f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                        f"Transmission ratio: {row['intensity']:.3f}<br>"
                        f"Relative to background: {row['intensity'] - 1.0:.3f}"
                        for _, row in wl_filtered.iterrows()
                    ]
            else:
                wl_text = [
                    f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                    f"Intensity: {row['intensity']:.2f}<br>"
                    f"Global %: {row['global_intensity_pct']:.1f}%"
                    for _, row in wl_filtered.iterrows()
                ]
            
            wavelength_buttons.append(dict(
                label=label,
                method="update",
                args=[{
                    "x": [wl_filtered['x'].tolist()], 
                    "y": [wl_filtered['y'].tolist()], 
                    "z": [wl_filtered['z'].tolist()],
                    "marker.size": [wl_filtered['size'].tolist()],
                    "marker.color": [wl_filtered['color'].tolist()],
                    "text": [wl_text]
                }]
            ))
    
    # Create buttons for intensity thresholds using global percentages (HIGHEST intensity)
    threshold_buttons = []
    
    for threshold in INTENSITY_THRESHOLD_STEPS:
        # Filter data for this intensity threshold percentage
        thresh_filtered = df[df['global_intensity_pct'] >= threshold]
        
        # Generate appropriate hover text based on normalization
        if is_normalized:
            if normalization_type == 'percentage':
                thresh_text = [
                    f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                    f"Transmission: {row['intensity']:.1f}%<br>"
                    f"Relative to background: {row['intensity'] - 100:.1f}%"
                    for _, row in thresh_filtered.iterrows()
                ]
            else:
                thresh_text = [
                    f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                    f"Transmission ratio: {row['intensity']:.3f}<br>"
                    f"Relative to background: {row['intensity'] - 1.0:.3f}"
                    for _, row in thresh_filtered.iterrows()
                ]
        else:
            thresh_text = [
                f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                f"Intensity: {row['intensity']:.2f}<br>"
                f"Global %: {row['global_intensity_pct']:.1f}%"
                for _, row in thresh_filtered.iterrows()
            ]
        
        # More compact label
        threshold_buttons.append(dict(
            label=f"≥ {threshold}%",
            method="update",
            args=[{
                "x": [thresh_filtered['x'].tolist()], 
                "y": [thresh_filtered['y'].tolist()], 
                "z": [thresh_filtered['z'].tolist()],
                "marker.size": [thresh_filtered['size'].tolist()],
                "marker.color": [thresh_filtered['color'].tolist()],
                "text": [thresh_text]
            }]
        ))
    
    # Create buttons for LOWEST intensity thresholds
    low_threshold_buttons = []
    
    for threshold in INTENSITY_THRESHOLD_STEPS:
        # For lowest intensity, we invert the condition:
        # Show only points BELOW the threshold percentage
        if threshold > 0:  # Skip the 0% threshold as it would include everything
            low_thresh_filtered = df[df['global_intensity_pct'] <= threshold]
            
            # Generate appropriate hover text based on normalization
            if is_normalized:
                if normalization_type == 'percentage':
                    low_thresh_text = [
                        f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                        f"Transmission: {row['intensity']:.1f}%<br>"
                        f"Relative to background: {row['intensity'] - 100:.1f}%"
                        for _, row in low_thresh_filtered.iterrows()
                    ]
                else:
                    low_thresh_text = [
                        f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                        f"Transmission ratio: {row['intensity']:.3f}<br>"
                        f"Relative to background: {row['intensity'] - 1.0:.3f}"
                        for _, row in low_thresh_filtered.iterrows()
                    ]
            else:
                low_thresh_text = [
                    f"Position: {row['position']}<br>Wavelength: {row['wavelength']:.2f}nm<br>"
                    f"Intensity: {row['intensity']:.2f}<br>"
                    f"Global %: {row['global_intensity_pct']:.1f}%"
                    for _, row in low_thresh_filtered.iterrows()
                ]
            
            # More compact label
            low_threshold_buttons.append(dict(
                label=f"≤ {threshold}%",
                method="update",
                args=[{
                    "x": [low_thresh_filtered['x'].tolist()], 
                    "y": [low_thresh_filtered['y'].tolist()], 
                    "z": [low_thresh_filtered['z'].tolist()],
                    "marker.size": [low_thresh_filtered['size'].tolist()],
                    "marker.color": [low_thresh_filtered['color'].tolist()],
                    "text": [low_thresh_text]
                }]
            ))
    
    # Update layout for better appearance
    # Prepare title with normalization info
    title = 'Interactive 3D Spectral Visualization'
    if is_normalized:
        if normalization_type == 'percentage':
            title += ' (Normalized to % Transmission)'
        else:
            title += ' (Normalized to Transmission Ratio)'
    
    fig.update_layout(
        title=dict(
            text=title,
            x=0.15,  # Move title to the left
            xanchor='left',
            font=dict(size=18)
        ),
        scene=dict(
            xaxis=dict(title='X Position', range=[-0.5, grid_width-0.5], 
                       tickmode='array', tickvals=list(range(grid_width))),
            yaxis=dict(title='Wavelength (nm)', range=[min(wavelengths), max(wavelengths)]),
            zaxis=dict(title='Y Position', range=[-0.5, grid_height-0.5],
                       tickmode='array', tickvals=list(range(grid_height))),
            aspectratio=SCENE_ASPECT_RATIO,
            camera=dict(
                eye=dict(x=1.5, y=1.5, z=1.2)
            ),
            dragmode='turntable'
        ),
        template=TEMPLATE,
        margin=dict(r=20, l=10, b=10, t=40),
        height=FIGURE_HEIGHT,
        # Move legend to bottom right, but keep the graph on left side
        legend=dict(
            yanchor="bottom",
            y=0.01,
            xanchor="right",
            x=0.99
        ),
        updatemenus=[
            # Wavelength filter dropdown
            dict(
                buttons=wavelength_buttons,
                direction="down",
                pad={"r": 10, "t": 10},
                showactive=True,
                x=0.5,  # Moved right
                xanchor="left",
                y=1.1,
                yanchor="top",
                name="wavelength_filter",
                bgcolor="rgba(50, 50, 50, 0.7)",
                font=dict(color="white", size=12),  # Adjusted font size
                active=0
            ),
            # Highest intensity threshold dropdown
            dict(
                buttons=threshold_buttons,
                direction="down",
                pad={"r": 10, "t": 10},
                showactive=True,
                x=0.7,  # Adjusted position
                xanchor="left",
                y=1.1,
                yanchor="top",
                name="high_intensity_threshold",
                bgcolor="rgba(50, 50, 50, 0.7)",
                font=dict(color="white", size=12),  # Adjusted font size
                active=0
            ),
            # Lowest intensity threshold dropdown
            dict(
                buttons=low_threshold_buttons,
                direction="down",
                pad={"r": 10, "t": 10},
                showactive=True,
                x=0.9,  # Adjusted position
                xanchor="left",
                y=1.1,
                yanchor="top",
                name="low_intensity_threshold",
                bgcolor="rgba(50, 50, 50, 0.7)",
                font=dict(color="white", size=12),  # Adjusted font size
                active=0
            )
        ]
    )
    
    # Position the 3D scene to the left side of the layout
    fig.update_layout(
        scene=dict(
            domain=dict(x=[0, 0.85], y=[0, 1])  # This positions the 3D scene on the left
        )
    )
    
    # Add annotation - moved to bottom right corner
    # Prepare annotation text with normalization info
    annotation_text = (f"Point color: {'' if is_normalized and USE_NORMALIZED_COLORSCALE else 'wavelength color + intensity darkening'}<br>"
                       f"Point size: {'deviation from background' if is_normalized else 'intensity'}<br>"
                       f"Contrast factor: {contrast_factor}<br>"
                       f"Snake pattern: {'enabled' if snake_pattern else 'disabled'}<br>"
                       f"Grid: {grid_width}x{grid_height}")
    
    # Add extra info for normalized data
    if is_normalized:
        if USE_NORMALIZED_COLORSCALE:
            if normalization_type == 'percentage':
                annotation_text += "<br>Color: Blue < 100%, White ≈ 100%, Red > 100%"
            else:
                annotation_text += "<br>Color: Blue < 1.0, White ≈ 1.0, Red > 1.0"
    
    fig.add_annotation(
        x=0.98,
        y=0.15,
        xref="paper",
        yref="paper",
        text=annotation_text,
        showarrow=False,
        font=dict(
            family="Arial",
            size=12,
            color="white"
        ),
        align="right",
        bgcolor="rgba(0,0,0,0.5)",
        bordercolor="white",
        borderwidth=1,
        borderpad=4
    )
    
    # Disable animation for better performance if requested
    if DISABLE_ANIMATION:
        fig.update_layout(
            transition_duration=0
        )
    
    # Make sure output directory exists
    if output_html is None:
        output_html = get_output_path(scan_dir, "3d_visualization.html")
    
    os.makedirs(os.path.dirname(output_html), exist_ok=True)
    
    # Save to HTML file to enable all interactive features
    fig.write_html(output_html)
    print(f"Interactive visualization saved to {output_html}")
    
    # Display the figure
    fig.show()
    
    print("Interactive visualization completed!")
    return fig

#=============================================================================
# 2D WAVELENGTH SLICE VISUALIZATION
#=============================================================================

def create_wavelength_slices(wavelengths, counts_cube, grid_width, grid_height, 
                           snake_pattern=False, max_wavelength_samples=100, wavelength_step=5):
    """
    Reorganize the data cube into wavelength slices - each slice is a 2D grid for a specific wavelength.
    Handles missing data points properly.
    """
    # Sample wavelengths if needed
    if len(wavelengths) > max_wavelength_samples:
        step = len(wavelengths) // max_wavelength_samples
        wavelength_indices = range(0, len(wavelengths), step)
        sampled_wavelengths = wavelengths[wavelength_indices]
    else:
        wavelength_indices = range(0, len(wavelengths), wavelength_step)
        sampled_wavelengths = wavelengths[wavelength_indices]
    
    print(f"Creating {len(sampled_wavelengths)} wavelength slices...")
    
    # Create empty wavelength slices - each is a 2D grid
    wavelength_slices = []
    
    # For each wavelength, create a 2D grid
    for wl_idx in wavelength_indices:
        # Extract data for this wavelength
        slice_data = np.zeros((grid_height, grid_width))
        slice_data.fill(np.nan)  # Fill with NaN to mark as missing initially
        
        # Fill in the slice with intensity values
        for spectrum_idx in range(min(counts_cube.shape[0], grid_width * grid_height)):
            # Calculate the grid position - important: now using x_idx and y_idx from filename
            y_idx = spectrum_idx // grid_width
            x_idx = spectrum_idx % grid_width
            
            # Check if we have valid data for this point
            if not np.isnan(counts_cube[spectrum_idx, wl_idx]):
                # Set intensity at this position (y axis is typically flipped in visualizations)
                slice_data[grid_height - 1 - y_idx, x_idx] = counts_cube[spectrum_idx, wl_idx]
        
        wavelength_slices.append(slice_data)
    
    return wavelength_slices, sampled_wavelengths

def create_wavelength_slider_visualization(wavelength_slices, sampled_wavelengths, 
                                          contrast_factor=CONTRAST_FACTOR,
                                          output_html=None, scan_dir=None,
                                          is_normalized=False, normalization_type=None):
    """
    Create an interactive visualization with a wavelength slider using Plotly.
    
    Parameters:
    - wavelength_slices: List of 2D arrays, each representing intensity at a specific wavelength
    - sampled_wavelengths: List of wavelength values corresponding to each slice
    - contrast_factor: Contrast enhancement factor for visualization
    - output_html: Output HTML file name or path
    - scan_dir: Scan directory to save output file
    - is_normalized: Whether data has been normalized against background
    - normalization_type: Type of normalization ('percentage' or 'ratio')
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        print("Successfully imported Plotly for visualization")
    except ImportError:
        print("Error: Plotly is not installed. Please install with 'pip install plotly'")
        return
    
    # Create a figure
    fig = go.Figure()
    
    # Get dimensions
    height, width = wavelength_slices[0].shape
    
    # Prepare title with normalization info
    title = "Wavelength Slice Visualization"
    if is_normalized:
        if normalization_type == 'percentage':
            title += " (Normalized to % Transmission)"
        else:
            title += " (Normalized to Transmission Ratio)"
    
    # Choose colorscale based on normalization
    if is_normalized and USE_NORMALIZED_COLORSCALE:
        if normalization_type == 'percentage':
            # For percentage, use RdBu_r: blue for <100%, white for ~100%, red for >100%
            colorscale = NORMALIZED_COLORSCALE
            # Set midpoint at reference value (100%)
            mid_val = 100
            # Set range (e.g., 0-200% by default)
            vmin, vmax = NORMALIZED_RANGE
            print(f"Using normalized colorscale: {colorscale} with range {vmin}-{vmax}%")
        else:
            # For ratio, similar concept but with 1.0 as reference
            colorscale = NORMALIZED_COLORSCALE
            mid_val = 1.0
            # Set range (e.g., 0-2.0 by default)
            vmin, vmax = [v/100 for v in NORMALIZED_RANGE]  # Convert percentage to ratio
            print(f"Using normalized colorscale: {colorscale} with range {vmin}-{vmax}")
    else:
        # Use standard colorscale for non-normalized data
        colorscale = COLORSCALE
        vmin, vmax = None, None
        print(f"Using standard colorscale: {colorscale}")
    
    # Calculate the maximum and minimum values for global intensity scale
    if GLOBAL_INTENSITY_SCALE:
        global_min = np.min([np.min(wl_slice) for wl_slice in wavelength_slices])
        global_max = np.max([np.max(wl_slice) for wl_slice in wavelength_slices])
        print(f"Global intensity range: {global_min:.2f} to {global_max:.2f}")
        
        # For normalized data, we may want to override the automatic range
        if is_normalized and vmin is not None and vmax is not None:
            global_min = vmin
            global_max = vmax
            print(f"Overriding with normalized range: {global_min:.2f} to {global_max:.2f}")
    else:
        global_min = None
        global_max = None
    
    # Enhance contrast if needed
    if contrast_factor != 1.0:
        enhanced_slices = []
        for slice_data in wavelength_slices:
            # Apply contrast enhancement
            if LOG_SCALE and np.max(slice_data) > 0:
                # Add a small value to avoid log(0)
                min_non_zero = np.min(slice_data[slice_data > 0]) if np.any(slice_data > 0) else 1e-6
                slice_data = np.log1p(slice_data + min_non_zero * 0.1)
            
            # Apply contrast factor
            enhanced_slice = slice_data ** contrast_factor
            enhanced_slices.append(enhanced_slice)
        
        wavelength_slices = enhanced_slices
    
    # Add a frame for each wavelength
    print("Creating frames for animation...")
    frames = []
    
    for i, (wl_slice, wavelength) in enumerate(zip(wavelength_slices, sampled_wavelengths)):
        # For normalized data with special colorscale, we use the configured colorscale
        if is_normalized and USE_NORMALIZED_COLORSCALE:
            current_colorscale = colorscale
        else:
            # For standard visualization, get true wavelength color
            r, g, b = wavelength_to_rgb(wavelength)
            
            # Create a customized colorscale based on the wavelength color
            current_colorscale = [
                [0, f'rgba({int(r*50)},{int(g*50)},{int(b*50)},1)'],  # Dark version of wavelength color
                [1, f'rgba({int(r*255)},{int(g*255)},{int(b*255)},1)']  # Bright version of wavelength color
            ]
        
        # Customize hover text based on normalization
        if is_normalized:
            if normalization_type == 'percentage':
                hovertemplate = 'X: %{x}<br>Y: %{y}<br>Transmission: %{z:.1f}%<extra></extra>'
            else:
                hovertemplate = 'X: %{x}<br>Y: %{y}<br>Transmission Ratio: %{z:.3f}<extra></extra>'
        else:
            hovertemplate = 'X: %{x}<br>Y: %{y}<br>Intensity: %{z:.2f}<extra></extra>'
        
        # Add a frame for this wavelength
        frames.append(
            go.Frame(
                data=[go.Heatmap(
                    z=wl_slice,
                    colorscale=current_colorscale,
                    showscale=True,
                    zmin=global_min,  # Use global min if enabled
                    zmax=global_max,  # Use global max if enabled
                    colorbar=dict(
                        title=dict(
                            text='Intensity' if not is_normalized else 
                                 'Transmission (%)' if normalization_type == 'percentage' else 'Transmission Ratio',
                            side='right',
                            font=dict(size=14)
                        ),
                        x=1.02,
                    ),
                    hovertemplate=hovertemplate,
                )],
                name=f"{wavelength:.2f}"
            )
        )
    
    # Set up initial display with the middle wavelength
    default_index = len(wavelength_slices) // 2
    initial_slice = wavelength_slices[default_index]
    initial_wavelength = sampled_wavelengths[default_index]
    
    # Get initial colorscale
    if is_normalized and USE_NORMALIZED_COLORSCALE:
        initial_colorscale = colorscale
    else:
        r, g, b = wavelength_to_rgb(initial_wavelength)
        initial_colorscale = [
            [0, f'rgba({int(r*50)},{int(g*50)},{int(b*50)},1)'],
            [1, f'rgba({int(r*255)},{int(g*255)},{int(b*255)},1)']
        ]
    
    # Customize hover text based on normalization
    if is_normalized:
        if normalization_type == 'percentage':
            initial_hovertemplate = 'X: %{x}<br>Y: %{y}<br>Transmission: %{z:.1f}%<extra></extra>'
        else:
            initial_hovertemplate = 'X: %{x}<br>Y: %{y}<br>Transmission Ratio: %{z:.3f}<extra></extra>'
    else:
        initial_hovertemplate = 'X: %{x}<br>Y: %{y}<br>Intensity: %{z:.2f}<extra></extra>'
    
    fig.add_trace(
        go.Heatmap(
            z=initial_slice,
            colorscale=initial_colorscale,
            showscale=True,
            zmin=global_min,
            zmax=global_max,
            colorbar=dict(
                title=dict(
                    text='Intensity' if not is_normalized else 
                         'Transmission (%)' if normalization_type == 'percentage' else 'Transmission Ratio',
                    side='right',
                    font=dict(size=14)
                ),
                x=1.02,
                thickness=20,
                ypad=10,
                xpad=20,
            ),
            hovertemplate=initial_hovertemplate,
        )
    )
    
    # Set frames
    fig.frames = frames
    
    # Calculate number of slider steps (limit to 20 for usability)
    num_steps = min(20, len(sampled_wavelengths))
    step_indices = [int(i * len(sampled_wavelengths) / num_steps) for i in range(num_steps)]
    
    # Add slider for wavelength
    sliders = [
        {
            "active": default_index,
            "yanchor": "top",
            "xanchor": "left",
            "currentvalue": {
                "font": {"size": 16},
                "prefix": "Wavelength: ",
                "suffix": " nm",
                "visible": True,
                "xanchor": "right"
            },
            "transition": {"duration": 50, "easing": "cubic-in-out"},
            "pad": {"b": 10, "t": 50},
            "len": 0.9,
            "x": 0.1,
            "y": 0,
            "steps": [
                {
                    "args": [
                        [f"{sampled_wavelengths[i]:.2f}"],
                        {
                            "frame": {"duration": 50, "redraw": True},
                            "mode": "immediate",
                            "transition": {"duration": 50}
                        }
                    ],
                    "label": f"{sampled_wavelengths[i]:.0f}",
                    "method": "animate"
                }
                for i in step_indices
            ]
        }
    ]
    
    # Set layout
    template = 'plotly_dark' if DARK_MODE else 'plotly_white'
    
    fig.update_layout(
        title=title,
        template=template,
        xaxis=dict(title="X Position"),
        yaxis=dict(title="Y Position", scaleanchor="x", scaleratio=1),
        sliders=sliders,
        updatemenus=[
            # Play/Pause buttons
            {
                "buttons": [
                    {
                        "args": [None, {"frame": {"duration": 500, "redraw": True}, "fromcurrent": True}],
                        "label": "▶ Play",
                        "method": "animate"
                    },
                    {
                        "args": [[None], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}],
                        "label": "⏸ Pause",
                        "method": "animate"
                    }
                ],
                "direction": "left",
                "pad": {"r": 10, "t": 0, "b": 10},
                "showactive": True,
                "type": "buttons",
                "x": 0.1,
                "xanchor": "right",
                "y": -0.05,
                "yanchor": "top",
                "bgcolor": "rgba(50, 50, 50, 0.7)",
                "font": {"color": "black"}
            },
            # Speed control dropdown
            {
                "buttons": [
                    {
                        "args": [None, {"frame": {"duration": 1000, "redraw": True}, "fromcurrent": True}],
                        "label": "0.5× Speed",
                        "method": "animate"
                    },
                    {
                        "args": [None, {"frame": {"duration": 500, "redraw": True}, "fromcurrent": True}],
                        "label": "1× Speed",
                        "method": "animate"
                    },
                    {
                        "args": [None, {"frame": {"duration": 250, "redraw": True}, "fromcurrent": True}],
                        "label": "2× Speed",
                        "method": "animate"
                    },
                    {
                        "args": [None, {"frame": {"duration": 125, "redraw": True}, "fromcurrent": True}],
                        "label": "4× Speed",
                        "method": "animate"
                    },
                    {
                        "args": [None, {"frame": {"duration": 50, "redraw": True}, "fromcurrent": True}],
                        "label": "10× Speed",
                        "method": "animate"
                    }
                ],
                "direction": "down",
                "pad": {"r": 10, "t": 0, "b": 10, "l": 10},
                "showactive": True,
                "type": "dropdown",
                "x": 0.15,
                "xanchor": "left",
                "y": -0.05,
                "yanchor": "top",
                "active": 1,
                "bgcolor": "rgba(50, 50, 50, 0.7)",
                "font": {"color": "black"}
            }
        ],
        autosize=True,
        height=FIGURE_HEIGHT,
        margin=dict(l=65, r=160, b=120, t=90),
    )
    
    # Make sure output directory exists
    if output_html is None:
        output_html = get_output_path(scan_dir, "2d_visualization.html")
    
    dir_path = os.path.dirname(output_html)
    if dir_path:  # Only create if there's a directory component
        os.makedirs(dir_path, exist_ok=True)
    
    # Save to HTML file
    config = {
        'responsive': True,
        'displayModeBar': True,
        'displaylogo': False,
        'modeBarButtonsToRemove': ['toImage', 'sendDataToCloud'],
        'scrollZoom': True
    }
    
    fig.write_html(
        output_html,
        include_plotlyjs=True,
        full_html=True,
        config=config
    )
    
    print(f"Interactive visualization saved to {output_html}")
    
    # Show the figure
    fig.show(config=config)
    
    return fig

#=============================================================================
# VISUALIZATION WRAPPER FUNCTION
#=============================================================================

def visualize_spectral_data(wavelengths, counts_cube, grid_width, grid_height, 
                           snake_pattern=SNAKE_PATTERN, contrast_factor=CONTRAST_FACTOR, 
                           visualization_type="3d", output_html=None,
                           metadata=None):
    """
    Main function to visualize spectral data.
    
    Parameters:
    - wavelengths: Array of wavelength values
    - counts_cube: Array of intensity values for each spectrum
    - grid_width: Width of the grid
    - grid_height: Height of the grid
    - snake_pattern: Whether to use snake pattern for visualization
    - contrast_factor: Contrast enhancement factor
    - visualization_type: Type of visualization ("3d" or "2d_slices")
    - output_html: Output HTML file name (default to preset values if None)
    - metadata: Dictionary of processing metadata
    
    Returns:
    - fig: Plotly figure object
    """
    # Get scan directory from metadata if available
    scan_dir = None
    if metadata is not None and 'scan_directory' in metadata:
        scan_dir = metadata['scan_directory']
    
    # Check if data is normalized based on metadata
    is_normalized = False
    normalization_type = None
    
    if metadata is not None and 'normalized' in metadata:
        is_normalized = metadata['normalized']
        normalization_type = metadata.get('normalization_type', None)
    
    if visualization_type == "3d":
        # 3D point cloud visualization
        if output_html is None:
            output_html = get_output_path(scan_dir, "3d_visualization.html")
            
        # Make sure output directory exists
        dir_path = os.path.dirname(output_html)
        if dir_path:  # Only create if there's a directory component
            os.makedirs(dir_path, exist_ok=True)
            
        fig = create_interactive_spectral_vis(
            wavelengths, counts_cube, grid_width, grid_height, 
            contrast_factor=contrast_factor, snake_pattern=snake_pattern,
            is_normalized=is_normalized, normalization_type=normalization_type,
            output_html=output_html, scan_dir=scan_dir
        )
        
    elif visualization_type == "2d_slices":

        if output_html is None:
            output_html = get_output_path(scan_dir, "2d_visualization.html")
        
        # Create wavelength slices using the local function
        wavelength_slices, sampled_wavelengths = create_wavelength_slices(
            wavelengths, counts_cube, grid_width, grid_height, snake_pattern
        )
        
        # Create visualization
        fig = create_wavelength_slider_visualization(
            wavelength_slices, sampled_wavelengths, 
            contrast_factor=contrast_factor, output_html=output_html,
            scan_dir=scan_dir,
            is_normalized=is_normalized, normalization_type=normalization_type
        )
        
    else:
        raise ValueError(f"Unknown visualization type: {visualization_type}")
    
    print(f"Visualization saved to {output_html}")
    return fig


#=============================================================================
# MAIN FUNCTION
#=============================================================================

def main():
    """Main function to run processing and visualization."""
    # Import the processor function
    from data_processing import process_spectral_data
    
    # Process the spectral data
    wavelengths, counts_cube, files, file_indices, grid_width, grid_height, features, metadata = process_spectral_data()
    
    # Create 2D slice visualization first
    print("\nCreating 2D wavelength slice visualization...")
    visualize_spectral_data(
        wavelengths, counts_cube, grid_width, grid_height,
        visualization_type="2d_slices",
        metadata=metadata
    )
    
    # Optionally create 3D visualization
    create_3d_vis = input("\nCreate 3D interactive visualization? (y/n): ").lower() == 'y'
    if create_3d_vis:
        print("\nCreating 3D interactive visualization...")
        visualize_spectral_data(
            wavelengths, counts_cube, grid_width, grid_height,
            visualization_type="3d",
            metadata=metadata
        )
    
    print("\nSpectral data visualization complete!")

if __name__ == "__main__":
    main()