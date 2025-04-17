# Hypermicro - an open-source scanning hyperspectral microscope

This project combines a spectrometer with a motion system to point-scan spectrometer readings across a microscope stage, creating hyperspectral images! The parts can be sourced and 3D printed for less than 100$. The code runs on a PC and an Arduino, controlling two stepper motors and synchronizing scan times with the spectrometer. Spectrometer data is organized and renamed with coordinate information during the scan, then post-processed into a data cube and visualized with two included visualization methods. As a point-scanning system, the capture speed depends on how long it takes to move to and scan each point. This simple system is able to scan about 1 point/second.

## Why Hyperspectral Imaging?
Imagine that just by looking at something you can understand what molecules it’s made from, and in what concentrations: that’s the difference between hyperspectral systems and our eyes or RGB cameras. You may have heard astronomers claim that far-away stars or planets are composed of specific elements, or wondered how scientists can say with certainty what molecules make up something. The most common method is probably spectroscopy. Different molecules interact with light differently, they have different “spectral signatures” (or “Colors.”) We can see some of these color differences with our eyes or a normal digital camera, but we usually can’t see enough spectral detail to say “okay this amount of these molecules are in this area.” Being able to see this color spectrum in extreme detail can allow us to identify the unique signatures of different molecules, or the ways  that different molecules affect the “color.” This tells us important things about material composition, like why plants change color when they are healthy or sick, how dirt and rocks change color depending on their mineral content, or how bacteria can change in color as they grow.

In a hyperspectral camera, every pixel in the image has detailed spectral data. Instead of photographing three color channels (RGB), hyperspectral imaging systems capture dozens or hundreds of color channels for every pixel in the image. In this platform, each pixel can have over 1000 different spectral measurements spanning about 300 to 1200nm.

### Electronics architecture:
![An image of the electronics architecture](https://github.com/user-attachments/assets/9a88a37b-ed58-4368-bbd2-e4cab2521c7f)

### Software architecture:
![An image of the software architecture](https://github.com/user-attachments/assets/e28b5293-8c33-4c03-9de7-03446077f875)
