import os
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
# Remove direct import of Axes3D to avoid conflicts
import seaborn as sns
from scipy.signal import find_peaks

contrast_factor = 16

def wavelength_to_rgb(wavelength, gamma=0.8):
    """Convert wavelength in nm to RGB color.
    
    Based on code by Dan Bruton: http://www.physics.sfasu.edu/astro/color/spectra.html
    """
    wavelength = float(wavelength)
    if wavelength < 380 or wavelength > 750:
        # Outside visible range - return dark gray
        return (0.3, 0.3, 0.3)
    
    # Initialize RGB values
    if wavelength < 440:
        # Violet to blue
        r = -(wavelength - 440) / (440 - 380)
        g = 0.0
        b = 1.0
    elif wavelength < 490:
        # Blue to cyan
        r = 0.0
        g = (wavelength - 440) / (490 - 440)
        b = 1.0
    elif wavelength < 510:
        # Cyan to green
        r = 0.0
        g = 1.0
        b = -(wavelength - 510) / (510 - 490)
    elif wavelength < 580:
        # Green to yellow
        r = (wavelength - 510) / (580 - 510)
        g = 1.0
        b = 0.0
    elif wavelength < 645:
        # Yellow to red
        r = 1.0
        g = -(wavelength - 645) / (645 - 580)
        b = 0.0
    else:
        # Red
        r = 1.0
        g = 0.0
        b = 0.0
    
    # Intensify colors - the eye is less sensitive at the edges of visible spectrum
    if wavelength < 420:
        factor = 0.3 + 0.7 * (wavelength - 380) / (420 - 380)
    elif wavelength > 700:
        factor = 0.3 + 0.7 * (750 - wavelength) / (750 - 700)
    else:
        factor = 1.0
    
    # Apply gamma correction and scale
    r = max(0, min(1, (r * factor) ** gamma))
    g = max(0, min(1, (g * factor) ** gamma))
    b = max(0, min(1, (b * factor) ** gamma))
    
    return (r, g, b)

def create_interactive_spectral_vis(wavelengths, counts_cube, grid_width=5, grid_height=5, contrast_factor=2.0):
    """
    Create an interactive 3D visualization of spectral data using Plotly.
    
    Parameters:
    - wavelengths: Array of wavelength values
    - counts_cube: Array of intensity values for each spectrum
    - grid_width: Width of the scanning grid (e.g., 5 for a 5x5 grid)
    - grid_height: Height of the scanning grid
    - contrast_factor: Multiplier to enhance contrast (higher = more contrast)
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        print("Successfully imported Plotly for interactive visualization")
    except ImportError:
        print("Error: Plotly is not installed. Please install with 'pip install plotly'")
        print("Falling back to matplotlib visualization")
        return
    
    print("Creating interactive 3D spectral visualization with Plotly...")
    print(f"Using contrast factor: {contrast_factor}")
    
    # Calculate the maximum intensity for normalization
    max_intensity = np.max(counts_cube)
    print(f"Maximum intensity: {max_intensity}")
    
    # Sample wavelengths for better performance if needed
    # For Plotly we can handle more points than with Matplotlib
    if len(wavelengths) > 100:
        print(f"Original wavelength points: {len(wavelengths)}")
        sample_rate = len(wavelengths) // 100 + 1
        wavelength_indices = range(0, len(wavelengths), sample_rate)
        sampled_wavelengths = wavelengths[wavelength_indices]
        print(f"Sampled wavelength points: {len(sampled_wavelengths)}")
    else:
        wavelength_indices = range(len(wavelengths))
        sampled_wavelengths = wavelengths
    
    # Pre-compute wavelength colors
    print("Computing wavelength colors...")
    
    # Create the figure
    fig = go.Figure()
    
    # Process each spectrum and add to figure
    for spectrum_idx in range(min(counts_cube.shape[0], grid_width * grid_height)):
        # Convert spectrum index to grid position
        grid_x = spectrum_idx % grid_width
        grid_z = grid_height - 1 - (spectrum_idx // grid_width)
        
        print(f"Processing spectrum {spectrum_idx+1} at position (x={grid_x}, z={grid_z})...")
        
        # Sample intensities for this spectrum
        sampled_counts = counts_cube[spectrum_idx][wavelength_indices]
        
        # Normalize intensities within this spectrum
        local_max = np.max(sampled_counts)
        if local_max > 0:
            normalized_local = sampled_counts / local_max
        else:
            normalized_local = np.zeros_like(sampled_counts)
        
        # Apply contrast enhancement
        enhanced_values = normalized_local ** contrast_factor
        
        # Calculate point sizes (proportional to intensity)
        sizes = 2 + enhanced_values * 10  # Scale from 2 to 20
        
        # Create arrays of x and z coordinates
        x_coords = np.full(len(sampled_wavelengths), grid_x)
        z_coords = np.full(len(sampled_wavelengths), grid_z)
        
        # Create RGBA colors that incorporate opacity directly
        colors = []
        for i, (wl, intensity) in enumerate(zip(sampled_wavelengths, enhanced_values)):
            # Get RGB color for this wavelength
            r, g, b = wavelength_to_rgb(wl)
            
            # Convert to 0-255 range and add alpha channel
            r_int = int(r * 255)
            g_int = int(g * 255)
            b_int = int(b * 255)
            
            # Use enhanced_values as alpha (opacity)
            alpha = min(1.0, max(0.1, float(intensity)))  # Ensure alpha is between 0.1 and 1.0
            
            # Create RGBA string
            color = f'rgba({r_int}, {g_int}, {b_int}, {alpha})'
            colors.append(color)
        
        # Add a scatter3d trace for this spectrum
        fig.add_trace(go.Scatter3d(
            x=x_coords,
            y=sampled_wavelengths,  # Wavelength on y-axis
            z=z_coords,
            mode='markers',
            marker=dict(
                size=sizes,
                color=colors,  # RGBA colors with opacity built in
                line=dict(width=0)  # No border
            ),
            name=f'Position ({grid_x}, {grid_z})',
            hovertemplate=(
                'X: %{x}<br>'
                'Wavelength: %{y:.2f} nm<br>'
                'Y: %{z}<br>'
                'Intensity: %{marker.size:.2f}'
            )
        ))
    
    # Update layout for better appearance
    fig.update_layout(
        title='Interactive 3D Spectral Visualization',
        scene=dict(
            xaxis=dict(title='X Position', range=[-0.5, grid_width-0.5], 
                       tickmode='array', tickvals=list(range(grid_width))),
            yaxis=dict(title='Wavelength (nm)', range=[min(wavelengths), max(wavelengths)]),
            zaxis=dict(title='Y Position', range=[-0.5, grid_height-0.5],
                       tickmode='array', tickvals=list(range(grid_height))),
            aspectratio=dict(x=1, y=2, z=1),
            camera=dict(
                eye=dict(x=1.5, y=1.5, z=1.2)
            ),
            dragmode='turntable'
        ),
        template='plotly_dark',
        margin=dict(r=20, l=10, b=10, t=40),
        height=800,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        ),
        updatemenus=[
            # Add a dropdown menu to filter by wavelength range
            dict(
                buttons=[
                    dict(
                        label="All Wavelengths",
                        method="update",
                        args=[{"visible": [True] * len(fig.data)}]
                    ),
                    dict(
                        label="Violet-Blue (400-490 nm)",
                        method="update",
                        args=[{
                            "visible": [
                                any((400 <= y <= 490) for y in fig.data[i]['y'])
                                for i in range(len(fig.data))
                            ]
                        }]
                    ),
                    dict(
                        label="Green (490-570 nm)",
                        method="update",
                        args=[{
                            "visible": [
                                any((490 <= y <= 570) for y in fig.data[i]['y'])
                                for i in range(len(fig.data))
                            ]
                        }]
                    ),
                    dict(
                        label="Yellow-Red (570-750 nm)",
                        method="update",
                        args=[{
                            "visible": [
                                any((570 <= y <= 750) for y in fig.data[i]['y'])
                                for i in range(len(fig.data))
                            ]
                        }]
                    )
                ],
                direction="down",
                pad={"r": 10, "t": 10},
                showactive=True,
                x=0.1,
                xanchor="left",
                y=1.1,
                yanchor="top"
            ),
        ]
    )
    
    # Add annotation
    fig.add_annotation(
        x=0.02,
        y=0.05,
        xref="paper",
        yref="paper",
        text=f"Point color: true wavelength color<br>Point size: intensity<br>Contrast factor: {contrast_factor}",
        showarrow=False,
        font=dict(
            family="Arial",
            size=12,
            color="white"
        ),
        align="left",
        bgcolor="rgba(0,0,0,0.5)",
        bordercolor="white",
        borderwidth=1,
        borderpad=4
    )
    
    # Save to HTML file to enable all interactive features
    output_file = "interactive_spectral_visualization.html"
    fig.write_html(output_file)
    print(f"Interactive visualization saved to {output_file}")
    
    # Display the figure
    fig.show()
    
    print("Interactive visualization completed!")
    return fig

def visualize_spectral_data(wavelengths, counts_cube, files, file_indices, grid_shape=(5, 5)):
    """Visualize the spectral data cube using interactive Plotly visualization."""
    # Create interactive visualization with the specified grid shape and a contrast factor
    grid_width, grid_height = grid_shape
    
    # Use the new interactive Plotly visualization
    create_interactive_spectral_vis(wavelengths, counts_cube, grid_width, grid_height, contrast_factor)

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

def load_spectral_data(file_pattern):
    """Load all spectrum files matching the pattern."""
    files = sorted(glob.glob(file_pattern))
    if not files:
        raise ValueError(f"No files found matching pattern: {file_pattern}")
    
    print(f"Found {len(files)} spectrum files")
    
    # First, determine if all files have the same wavelength values
    wavelengths_list = []
    counts_list = []
    file_indices = []
    
    for file in files:
        # Extract file index for organizing the data cube
        try:
            file_index = int(os.path.basename(file).split('_')[1].split('.')[0])
            file_indices.append(file_index)
        except:
            # If parsing fails, just use sequential numbering
            file_indices.append(len(file_indices) + 1)
            
        wavelengths, counts = read_spectrum_file(file)
        if wavelengths is not None:
            wavelengths_list.append(wavelengths)
            counts_list.append(counts)
    
    # Check if all wavelength arrays are identical
    same_wavelengths = all(np.array_equal(wavelengths_list[0], w) for w in wavelengths_list)
    
    if same_wavelengths:
        print("All spectrum files have identical wavelength values")
        # Create data cube directly
        common_wavelengths = wavelengths_list[0]
        counts_cube = np.array(counts_list)
    else:
        print("Spectrum files have different wavelength values - interpolating to common grid")
        # Create a common wavelength grid
        all_wavelengths = np.concatenate(wavelengths_list)
        min_wavelength = np.min(all_wavelengths)
        max_wavelength = np.max(all_wavelengths)
        
        # Use the most common step size
        step_sizes = [np.median(np.diff(w)) for w in wavelengths_list]
        common_step = np.median(step_sizes)
        
        common_wavelengths = np.arange(min_wavelength, max_wavelength + common_step/2, common_step)
        
        # Interpolate all spectra to this common grid
        counts_cube = np.zeros((len(counts_list), len(common_wavelengths)))
        for i, (wavelengths, counts) in enumerate(zip(wavelengths_list, counts_list)):
            counts_cube[i] = np.interp(common_wavelengths, wavelengths, counts)
    
    return common_wavelengths, counts_cube, files, file_indices

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

def main():
    # File pattern to match all 25 files in the scan1 folder
    scan_folder = os.path.join("scan1")
    file_pattern = os.path.join(scan_folder, "SpectrumFile_*.txt")
    
    # Load the spectral data
    wavelengths, counts_cube, files, file_indices = load_spectral_data(file_pattern)
    
    # Extract features from the spectra
    features = extract_spectral_features(wavelengths, counts_cube)
    
    # Print some basic statistics
    print(f"\nSpectral Data Summary:")
    print(f"Number of spectra: {counts_cube.shape[0]}")
    print(f"Wavelength range: {min(wavelengths):.2f} to {max(wavelengths):.2f} nm")
    print(f"Average max intensity: {np.mean(features['max_intensity']):.2f}")
    print(f"Average peak wavelength: {np.mean(features['peak_wavelength']):.2f} nm")
    
    # Visualize the data
    visualize_spectral_data(wavelengths, counts_cube, files, file_indices)
    
    # Save the data cube for future use
    np.savez("spectral_data_cube.npz", 
             wavelengths=wavelengths, 
             counts_cube=counts_cube, 
             file_indices=np.array(file_indices))
    
    print("Spectral data analysis complete!")
    print("Data cube saved to 'spectral_data_cube.npz'")

if __name__ == "__main__":
    main()