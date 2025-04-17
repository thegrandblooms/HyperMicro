import os
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
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
import visualization

#=============================================================================
# CONFIGURATION PARAMETERS - Data Processing
#=============================================================================

# Data Location Settings
ORGANIZED_SCANS_DIR = "organized_scans"                # Base directory for organized scan data
SCAN_FOLDER = "scan"                                   # Legacy folder containing spectrum files
FILE_PATTERN = "scan_*_x*_y*.txt"                      # Pattern to match organized spectrum files

# Processing Status Tracking
PROCESSING_MARKER_FILE = "processing_complete.json"    # File to mark processed scans

# Normalization Settings
SPECTRAL_NORMALIZATION = False                         # Whether to normalize against background spectrum
BACKGROUND_SPECTRUM_FOLDER = "background"              # Folder containing background spectrum files
BACKGROUND_SPECTRUM_FILE = None                        # Single background file (used if not None, overrides folder)
MIN_BACKGROUND_INTENSITY = 0.01                        # Minimum background intensity to prevent division by zero
NORMALIZE_TO_PERCENTAGE = True                         # Convert normalized values to percentages (0-100%)

# Wavelength Filtering Settings
LOW_INTENSITY_FILTER_ENABLED = True                    # Whether to filter out wavelengths with low light source intensity
LOW_INTENSITY_THRESHOLD_PCT = 5.0                      # Exclude wavelengths where light source is below this % of its maximum
KEEP_WAVELENGTH_INDICES = False                        # Whether to keep original wavelength indices after filtering

# Data Processing Settings
SNAKE_PATTERN = True                                   # Whether to use snake pattern for visualization
REORDER_DATA = False                                   # Whether to reorder linearly collected data to match snake pattern
AUTO_DETECT_GRID = True                                # Whether to auto-detect grid dimensions from filenames
GRID_WIDTH = 128                                       # Manual grid width (used if AUTO_DETECT_GRID is False)
GRID_HEIGHT = 128                                      # Manual grid height (used if AUTO_DETECT_GRID is False)

# Output Settings
SAVE_DATA_CUBE = True                                  # Whether to save processed data cube
DATA_CUBE_FILENAME = "spectral_data_cube.npz"          # Output data cube file name
VISUALIZATION_OUTPUT_FILENAME = "visualization.html"   # Output visualization filename
GENERATE_3D_VIS = False                                # Set to True to automatically generate 3D visualizations
PROMPT_FOR_3D_VIS = True                               # Set to False to skip the prompt and use GENERATE_3D_VIS setting

# Processing Option Flags
PROCESS_ALL = False                                    # If True, process all scans even if already processed
VERBOSE_OUTPUT = True                                  # Enable verbose console output

#=============================================================================
# SCAN MANAGEMENT FUNCTIONS
#=============================================================================

def get_all_scan_directories():
    """
    Get all scan directories in the organized scans folder.
    
    Returns:
        List of scan directory paths
    """
    if not os.path.exists(ORGANIZED_SCANS_DIR):
        print(f"Organized scans directory not found: {ORGANIZED_SCANS_DIR}")
        return []
    
    # Get all subdirectories in the organized scans folder
    scan_dirs = [d for d in glob.glob(os.path.join(ORGANIZED_SCANS_DIR, "*")) 
                if os.path.isdir(d)]
    
    if not scan_dirs:
        print(f"No scan directories found in {ORGANIZED_SCANS_DIR}")
    else:
        print(f"Found {len(scan_dirs)} scan directories")
    
    return sorted(scan_dirs)

def get_unprocessed_scan_directories():
    """
    Get all unprocessed scan directories.
    
    Returns:
        List of unprocessed scan directory paths
    """
    all_dirs = get_all_scan_directories()
    unprocessed = []
    
    for scan_dir in all_dirs:
        # Check if processing marker file exists
        marker_file = os.path.join(scan_dir, PROCESSING_MARKER_FILE)
        data_cube_file = os.path.join(scan_dir, DATA_CUBE_FILENAME)
        
        if not os.path.exists(marker_file) and not os.path.exists(data_cube_file):
            unprocessed.append(scan_dir)
    
    print(f"Found {len(unprocessed)} unprocessed scan directories")
    return unprocessed

def mark_scan_as_processed(scan_dir, metadata):
    """
    Mark a scan as processed by creating a marker file with metadata.
    
    Args:
        scan_dir: Path to scan directory
        metadata: Dictionary of processing metadata
    """
    marker_file = os.path.join(scan_dir, PROCESSING_MARKER_FILE)
    
    # Add processing timestamp
    metadata['processing_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Convert numpy arrays to lists for JSON serialization
    json_safe_metadata = {}
    for key, value in metadata.items():
        if isinstance(value, np.ndarray):
            json_safe_metadata[key] = value.tolist()  # Convert ndarray to list
        elif isinstance(value, np.integer):
            json_safe_metadata[key] = int(value)  # Convert numpy int to Python int
        elif isinstance(value, np.floating):
            json_safe_metadata[key] = float(value)  # Convert numpy float to Python float
        elif isinstance(value, bool) or value is None or isinstance(value, (int, float, str)):
            json_safe_metadata[key] = value  # Keep Python primitives as is
        else:
            # For other types, convert to string
            json_safe_metadata[key] = str(value)
    
    # Create marker file with metadata
    with open(marker_file, 'w') as f:
        json.dump(json_safe_metadata, f, indent=2)
    
    print(f"Marked scan as processed: {os.path.basename(scan_dir)}")

def extract_grid_indices_from_filename(filename):
    """
    Extract X and Y grid indices from an organized filename.
    
    Args:
        filename: Filename in format scan_SCANID_xXXX_yYYY.txt
        
    Returns:
        Tuple of (x_idx, y_idx) or None if parsing fails
    """
    try:
        # Extract x and y indices
        base = os.path.basename(filename)
        x_part = base.split('_x')[1].split('_')[0]
        y_part = base.split('_y')[1].split('.')[0]
        
        x_idx = int(x_part)
        y_idx = int(y_part)
        
        return (x_idx, y_idx)
    except Exception as e:
        print(f"Error parsing grid indices from filename {filename}: {e}")
        return None

def detect_grid_dimensions_from_filenames(files):
    """
    Detect grid dimensions from organized filenames.
    
    Args:
        files: List of organized spectrum files
        
    Returns:
        Tuple of (grid_width, grid_height)
    """
    x_indices = set()
    y_indices = set()
    
    for file in files:
        indices = extract_grid_indices_from_filename(file)
        if indices:
            x_idx, y_idx = indices
            x_indices.add(x_idx)
            y_indices.add(y_idx)
    
    if not x_indices or not y_indices:
        print("Failed to extract grid indices from filenames")
        return None, None
    
    grid_width = max(x_indices) + 1
    grid_height = max(y_indices) + 1
    
    print(f"Detected grid dimensions from filenames: {grid_width}x{grid_height}")
    print(f"X indices: {min(x_indices)}-{max(x_indices)}, Y indices: {min(y_indices)}-{max(y_indices)}")
    
    return grid_width, grid_height

#=============================================================================
# MODIFIED DATA LOADING FUNCTIONS
#=============================================================================

def load_spectral_data_from_scan_dir(scan_dir, reorder_snake_pattern=False):
    """
    Load all spectrum files from a scan directory using explicit positioning from filenames.
    
    Args:
        scan_dir: Path to scan directory
        reorder_snake_pattern: Not needed anymore as we'll use explicit positions
    
    Returns:
        wavelengths: Array of wavelength values
        counts_cube: Array of intensity values for each spectrum
        files: List of file paths
        file_indices: List of (x_idx, y_idx) tuples
    """
    # Find all spectrum files in the scan directory
    files = glob.glob(os.path.join(scan_dir, FILE_PATTERN))
    
    if not files:
        print(f"No spectrum files found in {scan_dir}")
        return None, None, [], []
    
    print(f"Found {len(files)} spectrum files in {scan_dir}")
    
    # Extract grid indices from filenames and find grid dimensions
    file_indices = []
    max_x_idx = 0
    max_y_idx = 0
    
    for file in files:
        indices = extract_grid_indices_from_filename(file)
        if indices:
            x_idx, y_idx = indices
            file_indices.append((x_idx, y_idx))
            max_x_idx = max(max_x_idx, x_idx)
            max_y_idx = max(max_y_idx, y_idx)
        else:
            print(f"Warning: Could not parse indices from filename: {file}")
    
    # Grid dimensions
    grid_width = max_x_idx + 1
    grid_height = max_y_idx + 1
    print(f"Detected grid dimensions: {grid_width}x{grid_height}")
    
    # First, load one file to determine wavelength values
    sample_file = files[0]
    wavelengths, _ = read_spectrum_file(sample_file)
    
    if wavelengths is None:
        print(f"Failed to read sample file: {sample_file}")
        return None, None, files, file_indices
    
    # Create a sparse data structure to handle missing points
    # We'll use a dictionary with (x_idx, y_idx) as keys
    data_dict = {}
    
    # Load each file into the correct position
    for file, (x_idx, y_idx) in zip(files, file_indices):
        wavelengths, counts = read_spectrum_file(file)
        if wavelengths is not None:
            data_dict[(x_idx, y_idx)] = counts
    
    # Convert to a dense data cube with missing values handled
    counts_cube = np.zeros((grid_height * grid_width, len(wavelengths)))
    
    for i, y_idx in enumerate(range(grid_height)):
        for j, x_idx in enumerate(range(grid_width)):
            # Calculate linear index for the grid position
            linear_idx = i * grid_width + j
            
            if (x_idx, y_idx) in data_dict:
                # We have data for this position
                counts_cube[linear_idx] = data_dict[(x_idx, y_idx)]
            else:
                # Missing data for this position
                # Options: 
                # 1. Fill with zeros (already done by initialization)
                # 2. Fill with interpolated values from neighbors
                # 3. Fill with NaN to clearly mark as missing
                counts_cube[linear_idx] = np.nan
                print(f"Warning: Missing data at position x={x_idx}, y={y_idx}")
    
    return wavelengths, counts_cube, files, file_indices

#=============================================================================
# MAIN BATCH PROCESSING FUNCTION
#=============================================================================

def process_all_unprocessed_scans():
    """
    Process all unprocessed scans in the organized scans directory.
    
    Returns:
        List of successfully processed scan directories
    """
    # Get unprocessed scans
    if PROCESS_ALL:
        scan_dirs = get_all_scan_directories()
        print("Processing ALL scan directories (including previously processed)")
    else:
        scan_dirs = get_unprocessed_scan_directories()
        print("Processing only UNPROCESSED scan directories")
    
    if not scan_dirs:
        print("No scans to process")
        return []
    
    # Process each scan
    successfully_processed = []
    
    for scan_dir in scan_dirs:
        scan_name = os.path.basename(scan_dir)
        print(f"\n=== Processing scan: {scan_name} ===")
        
        try:
            # Process this scan
            success, metadata = process_single_scan(scan_dir)
            
            if success:
                # Mark as processed and add to successful list
                mark_scan_as_processed(scan_dir, metadata)
                successfully_processed.append(scan_dir)
                print(f"✅ Successfully processed scan: {scan_name}")
            else:
                print(f"❌ Failed to process scan: {scan_name}")
        except Exception as e:
            print(f"Error processing scan {scan_name}: {e}")
            import traceback
            print(traceback.format_exc())
    
    print(f"\nProcessing complete: {len(successfully_processed)}/{len(scan_dirs)} scans successful")
    return successfully_processed

def process_single_scan(scan_dir):
    """
    Process a single scan directory.
    
    Args:
        scan_dir: Path to scan directory
        
    Returns:
        (success, metadata) tuple
    """
    print(f"Processing scan: {os.path.basename(scan_dir)}")
    
    # Load spectral data
    wavelengths, counts_cube, files, file_indices = load_spectral_data_from_scan_dir(scan_dir)
    
    if wavelengths is None or counts_cube is None or len(files) == 0:
        print("Failed to load spectral data")
        return False, {}
    
    # Initialize metadata dictionary
    metadata = {
        'normalized': False,
        'normalization_type': None,
        'background_source': None,
        'wavelength_filtered': False,
        'original_wavelength_count': len(wavelengths),
        'filtered_wavelength_count': len(wavelengths),
        'processing_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'scan_directory': scan_dir,
        'file_count': len(files)
    }
    
    # Load background spectrum if we're normalizing or filtering
    bg_wavelengths, bg_counts, bg_success = None, None, False
    
    if SPECTRAL_NORMALIZATION or LOW_INTENSITY_FILTER_ENABLED:
        # Load background spectrum
        bg_wavelengths, bg_counts, bg_success = load_background_spectrum()
        
        if not bg_success:
            print("Warning: Failed to load background spectrum")
            if SPECTRAL_NORMALIZATION:
                print("✗ Background normalization will be skipped")
            if LOW_INTENSITY_FILTER_ENABLED:
                print("✗ Wavelength filtering will be skipped")
    
    # Filter out low intensity wavelengths if requested and we have background data
    if LOW_INTENSITY_FILTER_ENABLED and bg_success:
        print("\nFiltering wavelengths with low light source intensity...")
        
        # Make sure background wavelengths match data wavelengths
        if not np.array_equal(wavelengths, bg_wavelengths):
            print("Interpolating background spectrum to match data wavelengths...")
            bg_counts_aligned = np.interp(wavelengths, bg_wavelengths, bg_counts)
        else:
            bg_counts_aligned = bg_counts
        
        # Filter wavelengths
        filtered_wavelengths, valid_indices, wavelength_mask = filter_low_intensity_wavelengths(
            wavelengths, bg_counts_aligned, threshold_pct=LOW_INTENSITY_THRESHOLD_PCT
        )
        
        # Update metadata
        metadata['wavelength_filtered'] = True
        metadata['original_wavelength_count'] = len(wavelengths)
        metadata['filtered_wavelength_count'] = len(filtered_wavelengths)
        metadata['wavelength_filter_threshold'] = LOW_INTENSITY_THRESHOLD_PCT
        
        if len(filtered_wavelengths) < len(wavelengths):
            # Filter the counts cube
            filtered_counts_cube = counts_cube[:, wavelength_mask]
            
            # Update wavelengths and counts_cube
            original_wavelengths = wavelengths.copy()
            wavelengths = filtered_wavelengths
            counts_cube = filtered_counts_cube
            
            # Store the wavelength mask for potential use in visualization
            metadata['wavelength_mask'] = wavelength_mask
            
            print(f"✓ Filtered from {len(original_wavelengths)} to {len(wavelengths)} wavelength points")
        else:
            print("✓ No wavelengths were filtered out (all above threshold)")
    
    # Apply background normalization if requested and we have background data
    if SPECTRAL_NORMALIZATION and bg_success:
        print("\nApplying background spectrum normalization...")
        
        # Apply normalization
        original_counts_cube = counts_cube.copy()  # Keep original data for reference
        counts_cube = normalize_spectra(counts_cube, wavelengths, bg_wavelengths, bg_counts, 
                                       to_percentage=NORMALIZE_TO_PERCENTAGE)
        
        # Update metadata
        metadata['normalized'] = True
        metadata['normalization_type'] = 'percentage' if NORMALIZE_TO_PERCENTAGE else 'ratio'
        metadata['background_source'] = BACKGROUND_SPECTRUM_FOLDER if BACKGROUND_SPECTRUM_FILE is None else BACKGROUND_SPECTRUM_FILE
        
        print("✓ Background normalization applied successfully")
    
    # Extract features from the spectra
    features = extract_spectral_features(wavelengths, counts_cube)
    
    # Auto-detect grid dimensions if requested
    if AUTO_DETECT_GRID:
        # Try from filenames first
        grid_width, grid_height = detect_grid_dimensions_from_filenames(files)
        
        # Fall back to data-based detection if needed
        if grid_width is None or grid_height is None:
            grid_width, grid_height = detect_grid_dimensions(counts_cube)
    
    # Add grid dimensions to metadata
    metadata['grid_width'] = grid_width
    metadata['grid_height'] = grid_height
    
    # Print some basic statistics
    print(f"\nSpectral Data Summary:")
    print(f"Number of spectra: {counts_cube.shape[0]}")
    print(f"Wavelength range: {min(wavelengths):.2f} to {max(wavelengths):.2f} nm")
    print(f"Number of wavelength points: {len(wavelengths)}")
    if metadata['wavelength_filtered']:
        filtered_pct = 100 * (1 - len(wavelengths) / metadata['original_wavelength_count'])
        print(f"Wavelength filtering: {filtered_pct:.1f}% of points removed")
    print(f"Average max intensity: {np.mean(features['max_intensity']):.2f}")
    print(f"Average peak wavelength: {np.mean(features['peak_wavelength']):.2f} nm")
    print(f"Grid dimensions: {grid_width}x{grid_height}")
    print(f"Normalization: {'Applied' if metadata['normalized'] else 'Not applied'}")
    
    # Save the data cube for future use
    if SAVE_DATA_CUBE:
        data_cube_path = os.path.join(scan_dir, DATA_CUBE_FILENAME)
        save_data_cube(wavelengths, counts_cube, file_indices, data_cube_path, metadata)
    
    # Create visualizations
    try:
        print("\nGenerating visualizations...")
        
        # 2D slice visualization first (always generate this)
        vis_2d_path = os.path.join(scan_dir, "2d_" + VISUALIZATION_OUTPUT_FILENAME)
        vis_2d = visualize_data(
            wavelengths, counts_cube, grid_width, grid_height,
            visualization_type="2d_slices", output_html=vis_2d_path,
            metadata=metadata
        )
        print(f"2D visualization saved to: {vis_2d_path}")
        
        # Add 2D visualization path to metadata
        metadata['visualization_2d_path'] = vis_2d_path
        
        create_3d_vis = GENERATE_3D_VIS

        if PROMPT_FOR_3D_VIS:
            create_3d_vis = input("\nCreate 3D interactive visualization? (y/n): ").lower() == 'y'
        
        if create_3d_vis:
            print("\nGenerating 3D visualization (this may take some time)...")
            vis_3d_path = os.path.join(scan_dir, "3d_" + VISUALIZATION_OUTPUT_FILENAME)
            vis_3d = visualize_data(
                wavelengths, counts_cube, grid_width, grid_height,
                visualization_type="3d", output_html=vis_3d_path,
                metadata=metadata
            )
            print(f"3D visualization saved to: {vis_3d_path}")
            
            # Add 3D visualization path to metadata
            metadata['visualization_3d_path'] = vis_3d_path
        else:
            print("Skipping 3D visualization generation.")
        
        print("✓ Visualizations generated successfully")
    except Exception as e:
        print(f"Error generating visualizations: {e}")
        print(traceback.format_exc())
    
    return True, metadata

def read_spectrum_file(file_path):
    """Read a spectrum file and return wavelengths and counts."""
    try:
        data = pd.read_csv(file_path, sep='\t')
        # Ensure column names are standardized
        if data.shape[1] == 2:
            data.columns = ["Nanometers", "Counts"]
        wavelengths = data["Nanometers"].values
        counts = data["Counts"].values
        return wavelengths, counts
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None, None

def load_background_spectrum(file_or_folder=None, pattern=None):
    """
    Load background spectrum from a single file or average multiple files in a folder.
    
    Parameters:
    - file_or_folder: Single file path or folder containing background spectra
    - pattern: File pattern to match if folder is provided
    
    Returns:
    - wavelengths: Array of wavelength values
    - bg_counts: Array of average counts for the background
    - success: Whether loading was successful
    """
    # Use default settings if not provided
    if file_or_folder is None:
        if BACKGROUND_SPECTRUM_FILE is not None:
            file_or_folder = BACKGROUND_SPECTRUM_FILE
        else:
            file_or_folder = BACKGROUND_SPECTRUM_FOLDER
    
    if pattern is None and os.path.isdir(file_or_folder):
        pattern = os.path.join(file_or_folder, "*.txt")
    
    print(f"\nLoading background spectrum from: {file_or_folder}")
    
    # Single file case
    if os.path.isfile(file_or_folder):
        print(f"Reading background spectrum from single file: {file_or_folder}")
        wavelengths, counts = read_spectrum_file(file_or_folder)
        
        if wavelengths is None:
            print("Error: Failed to load background spectrum file")
            return None, None, False
        
        print(f"Background spectrum loaded: {len(wavelengths)} wavelength points")
        return wavelengths, counts, True
    
    # Folder with multiple files case
    elif os.path.isdir(file_or_folder):
        files = sorted(glob.glob(pattern))
        
        if not files:
            print(f"Error: No background spectrum files found matching pattern: {pattern}")
            return None, None, False
        
        print(f"Found {len(files)} background spectrum files to average")
        
        # Load all spectra
        wavelengths_list = []
        counts_list = []
        
        for file in files:
            wavelengths, counts = read_spectrum_file(file)
            if wavelengths is not None:
                wavelengths_list.append(wavelengths)
                counts_list.append(counts)
        
        if not wavelengths_list:
            print("Error: Failed to load any background spectrum files")
            return None, None, False
        
        # Check if all wavelength arrays are identical
        same_wavelengths = all(np.array_equal(wavelengths_list[0], w) for w in wavelengths_list)
        
        if same_wavelengths:
            print("All background files have identical wavelength values")
            # Average the counts
            common_wavelengths = wavelengths_list[0]
            bg_counts = np.mean(counts_list, axis=0)
        else:
            print("Background files have different wavelength values - interpolating to common grid")
            # Create a common wavelength grid
            all_wavelengths = np.concatenate(wavelengths_list)
            min_wavelength = np.min(all_wavelengths)
            max_wavelength = np.max(all_wavelengths)
            
            # Use the most common step size
            step_sizes = [np.median(np.diff(w)) for w in wavelengths_list]
            common_step = np.median(step_sizes)
            
            common_wavelengths = np.arange(min_wavelength, max_wavelength + common_step/2, common_step)
            
            # Interpolate all spectra to this common grid and average
            interpolated_counts = np.zeros((len(counts_list), len(common_wavelengths)))
            for i, (wl, counts) in enumerate(zip(wavelengths_list, counts_list)):
                interpolated_counts[i] = np.interp(common_wavelengths, wl, counts)
            
            bg_counts = np.mean(interpolated_counts, axis=0)
        
        print(f"Background spectrum averaged: {len(common_wavelengths)} wavelength points")
        return common_wavelengths, bg_counts, True
    
    else:
        print(f"Error: Background spectrum source not found: {file_or_folder}")
        return None, None, False

def filter_low_intensity_wavelengths(wavelengths, bg_counts, threshold_pct=LOW_INTENSITY_THRESHOLD_PCT):
    """
    Filter out wavelengths where background light source intensity is below a threshold.
    
    Parameters:
    - wavelengths: Array of wavelength values
    - bg_counts: Array of intensity values for the background (light source)
    - threshold_pct: Threshold percentage of maximum background intensity
    
    Returns:
    - filtered_wavelengths: Array of wavelength values after filtering
    - valid_indices: Array of indices of valid wavelengths
    - mask: Boolean mask where True indicates a wavelength to keep
    """
    if bg_counts is None or len(bg_counts) == 0:
        print("Warning: No background spectrum provided for filtering - returning all wavelengths")
        return wavelengths, np.arange(len(wavelengths)), np.ones(len(wavelengths), dtype=bool)

    # Calculate the maximum background intensity
    bg_max = np.max(bg_counts)
    
    # Calculate the threshold value
    threshold = bg_max * (threshold_pct / 100.0)
    print(f"Filtering wavelengths with intensity below {threshold_pct:.1f}% of maximum ({threshold:.2f} counts)")
    
    # Create a mask for wavelengths that meet the threshold
    mask = bg_counts >= threshold
    
    # Get valid indices
    valid_indices = np.where(mask)[0]
    
    # Get filtered wavelengths
    filtered_wavelengths = wavelengths[mask]
    
    # Report how many wavelengths were filtered
    original_count = len(wavelengths)
    filtered_count = len(filtered_wavelengths)
    removed_count = original_count - filtered_count
    removed_pct = (removed_count / original_count) * 100 if original_count > 0 else 0
    
    if removed_count > 0:
        # Determine the ranges of filtered wavelengths for better reporting
        ranges = []
        start_idx = None
        
        for i in range(len(wavelengths)):
            if not mask[i] and start_idx is None:
                # Start of a new filtered range
                start_idx = i
            elif mask[i] and start_idx is not None:
                # End of a filtered range
                ranges.append((wavelengths[start_idx], wavelengths[i-1]))
                start_idx = None
        
        # Check if we ended on a filtered range
        if start_idx is not None:
            ranges.append((wavelengths[start_idx], wavelengths[-1]))
        
        # Report the filtered ranges
        print(f"Filtered out {removed_count} wavelengths ({removed_pct:.1f}% of total)")
        if len(ranges) <= 5:  # Only show details for a reasonable number of ranges
            for i, (start_wl, end_wl) in enumerate(ranges):
                print(f"  Range {i+1}: {start_wl:.2f} - {end_wl:.2f} nm")
        else:
            print(f"  Found {len(ranges)} distinct wavelength ranges to filter")
    else:
        print("No wavelengths were filtered out")
    
    return filtered_wavelengths, valid_indices, mask

def normalize_spectra(counts_cube, wavelengths, bg_wavelengths, bg_counts, to_percentage=NORMALIZE_TO_PERCENTAGE):
    """
    Normalize spectra against a background spectrum.
    
    Parameters:
    - counts_cube: Array of intensity values for each spectrum
    - wavelengths: Array of wavelength values for counts_cube
    - bg_wavelengths: Array of wavelength values for the background
    - bg_counts: Array of counts for the background
    - to_percentage: Whether to convert to percentage transmission
    
    Returns:
    - normalized_counts_cube: Normalized intensity values
    """
    print(f"\nApplying background spectrum normalization")
    
    # Check if wavelength ranges match
    if not np.array_equal(wavelengths, bg_wavelengths):
        print("Wavelength ranges don't match - interpolating background to match data")
        bg_counts_interpolated = np.interp(wavelengths, bg_wavelengths, bg_counts)
    else:
        bg_counts_interpolated = bg_counts
    
    # Apply minimum threshold to prevent division by zero
    bg_counts_safe = np.maximum(bg_counts_interpolated, MIN_BACKGROUND_INTENSITY)
    
    # Normalize each spectrum
    normalized_counts_cube = np.zeros_like(counts_cube)
    for i in range(counts_cube.shape[0]):
        normalized_counts = counts_cube[i] / bg_counts_safe
        
        # Convert to percentage if requested
        if to_percentage:
            normalized_counts *= 100
        
        normalized_counts_cube[i] = normalized_counts
    
    # Calculate stats to report
    min_value = np.min(normalized_counts_cube)
    max_value = np.max(normalized_counts_cube)
    mean_value = np.mean(normalized_counts_cube)
    
    if to_percentage:
        print(f"Normalized to percentage transmission: min={min_value:.2f}%, mean={mean_value:.2f}%, max={max_value:.2f}%")
    else:
        print(f"Normalized to ratio: min={min_value:.4f}, mean={mean_value:.4f}, max={max_value:.4f}")
    
    return normalized_counts_cube

def visualize_data(wavelengths, counts_cube, grid_width, grid_height, 
                  visualization_type="3d", output_html=None, metadata=None):
    """Wrapper function to call visualization module"""
    import visualization
    
    return visualization.visualize_spectral_data(
        wavelengths, counts_cube, grid_width, grid_height,
        visualization_type=visualization_type, 
        output_html=output_html,
        metadata=metadata
    )

def extract_spectral_features(wavelengths, counts_cube):
    """Extract various features from the spectral data."""
    features = {
        'max_intensity': np.max(counts_cube, axis=1),
        'peak_wavelength': wavelengths[np.argmax(counts_cube, axis=1)],
        'mean_intensity': np.mean(counts_cube, axis=1),
        'total_intensity': np.sum(counts_cube, axis=1),
    }
    
    # Find peaks in each spectrum
    peaks_list = []
    for i in range(counts_cube.shape[0]):
        peaks, _ = find_peaks(counts_cube[i], height=np.mean(counts_cube[i]), distance=20)
        peaks_list.append(wavelengths[peaks])
    
    features['peaks'] = peaks_list
    
    return features

def detect_grid_dimensions(counts_cube):
    """
    Auto-detect grid dimensions from data.
    
    Parameters:
    - counts_cube: Array of intensity values for each spectrum
    
    Returns:
    - grid_width: Detected grid width
    - grid_height: Detected grid height
    """
    num_spectra = counts_cube.shape[0]
    grid_size = int(np.sqrt(num_spectra))
    
    if grid_size**2 == num_spectra:
        # Perfect square
        grid_width = grid_height = grid_size
    else:
        # Not a perfect square, find the best fit
        best_aspect_ratio = float('inf')
        best_width = best_height = grid_size
        
        for width in range(1, num_spectra + 1):
            height = (num_spectra + width - 1) // width  # Ceiling division
            if width * height >= num_spectra:  # Must be enough cells
                aspect_ratio = abs(width / height - 1.0)  # How close to square
                if aspect_ratio < best_aspect_ratio:
                    best_aspect_ratio = aspect_ratio
                    best_width = width
                    best_height = height
        
        grid_width = best_width
        grid_height = best_height
    
    print(f"Detected grid dimensions: {grid_width}x{grid_height}")
    return grid_width, grid_height

def save_data_cube(wavelengths, counts_cube, file_indices=None, filename=DATA_CUBE_FILENAME, 
                  metadata=None):
    """
    Save the data cube to a file for future use.
    
    Parameters:
    - wavelengths: Array of wavelength values
    - counts_cube: Array of intensity values for each spectrum
    - file_indices: List of file indices (optional)
    - filename: Output filename
    - metadata: Dictionary of additional metadata (optional)
    """
    # Make sure output directory exists
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    # Create dictionary with required data
    save_dict = {
        'wavelengths': wavelengths, 
        'counts_cube': counts_cube
    }
    
    # Add optional data
    if file_indices is not None:
        save_dict['file_indices'] = np.array(file_indices)
    
    # Add metadata if provided
    if metadata is not None:
        for key, value in metadata.items():
            if isinstance(value, np.ndarray):
                save_dict[key] = value
            else:
                # Convert non-ndarray values to string for compatibility
                save_dict[key] = str(value)
    
    # Save to NPZ file
    np.savez(filename, **save_dict)
    
    print(f"Data cube saved to '{filename}'")

#=============================================================================
# MAIN FUNCTION
#=============================================================================

if __name__ == "__main__":
    # Process all unprocessed scans
    processed_scans = process_all_unprocessed_scans()
    
    if processed_scans:
        print("\nSuccessfully processed scans:")
        for scan_dir in processed_scans:
            print(f"  - {os.path.basename(scan_dir)}")
        
        print("\nTo view visualizations, open the HTML files in each scan directory.")
    else:
        print("\nNo scans were successfully processed.")