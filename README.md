# An open-source scanning hyperspectral microscope

This project combines a spectrometer with a motorized motion system to point-scan spectrometer readings across a microscope stage, creating hyperspectral images! The parts can be sourced and 3D printed for less than 100$. The code runs on a PC and an Arduino, controlling two stepper motors and synchronizing scan times with the spectrometer. Spectrometer data is organized and renamed with coordinate information during the scan, then post-processed into a data cube and visualized with two included visualization methods.

As a point-scanning system, the capture speed depends on how long it takes to move to and scan each point. This simple system is able to scan about 1 point/second.

### Electronics architecture:
![An image of the electronics architecture](https://github.com/user-attachments/assets/9a88a37b-ed58-4368-bbd2-e4cab2521c7f)

### Software architecture:
![An image of the software architecture](https://github.com/user-attachments/assets/e28b5293-8c33-4c03-9de7-03446077f875)
