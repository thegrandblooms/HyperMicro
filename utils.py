import numpy as np

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