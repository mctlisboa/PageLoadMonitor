# Page Load Monitor

A simple Flask-based application that measures **Connection Time**, **Latency**, **Response Time**, and **Page Load Time** for multiple websites using **pycurl**. It stores the results in a CSV and displays charts in a web dashboard.

## Features

- **Add and Remove Sites** to monitor at runtime.  
- **Set Measurement Interval** (in minutes) directly from the UI.  
- **Four Metrics** in milliseconds:  
  - **Connection Time**  
  - **Latency** (TTFB)  
  - **Response Time** (TTFB to finish)  
  - **Page Load Time** (overall)  
- **CSV Storage** with a download link.  
- **15-Minute Block Stats** for the last 24 hours (lowest and highest load times).  

## Getting Started

### 1. Build the Docker Image

```bash
docker build -t page-load-monitor:latest .
```

This uses the provided `Dockerfile`, which installs the necessary dependencies, including **pycurl**.

### 2. Run the Container

```bash
docker run -d \
  -p 5000:5000 \
  --name page_monitor \
  page-load-monitor:latest
```

**Optional**: Mount a volume to **persist** the CSV data across restarts:

```bash
docker run -d \
  -p 5000:5000 \
  -v /host/path:/app \
  --name page_monitor \
  page-load-monitor:latest
```

### 3. Access the Dashboard

Open your browser and go to:

```
http://localhost:5000
```

You can then:

- **Add a site** (e.g., `https://www.example.com`).  
- **Set the measurement frequency** (in minutes).  
- **Remove** any unwanted site from the list.  
- **Download** the CSV file of measurements at any time.

### Notes

- The **Page Load Monitor** uses a **background thread** to measure all sites every *N* minutes (based on the interval you set).  
- You can see a real-time chart for each site, plotting the four metrics (ms) on a timeline.  

## License

This project is distributed under the MIT License. See [LICENSE](./LICENSE) for details.
