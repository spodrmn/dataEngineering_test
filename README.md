This script processes referral data, cleans it, and flags potentially fraudulent rewards.

Files:
-main.py - main python script 
-profiling.py - data profiling script
-Dockerfile - docker setup
-requirements.txt - dependencies
-documentation.xlsx - data dictionary and profiling results
-data/ - put your CSV files here
-output/ - reports get saved here


Requirements
-Docker Desktop installed and running
-All 7 CSV files inside the data/ folder


How to run
1. Make sure Docker Desktop is open
2. Build the image (only need to do this once, or after changing code):
  docker build -t springer-pipeline .
3. Run the pipeline:
  Windows CMD:
    docker run -v %cd%/data:/app/data -v %cd%/output:/app/output springer-pipeline
  Mac/Linux:
    docker run -v $(pwd)/data:/app/data -v $(pwd)/output:/app/output springer-pipeline

The report will be saved to output/referral_report.csv


Running the profiling script:
-Same as above but add python profiling.py at the end:
  Windows CMD:
    docker run -v %cd%/data:/app/data -v %cd%/output:/app/output springer-pipeline python profiling.py


Running without Docker:
-If you have Python 3.11 installed:
  pip install -r requirements.txt
  python profiling.py
  python main.py

  
Cloud storage credentials:
If you need to upload the report to S3 or GCS, pass credentials as environment variables at runtime. Never put credentials in the script.

AWS S3 example:
    docker run -e AWS_ACCESS_KEY_ID=your_key -e 
    AWS_SECRET_ACCESS_KEY=your_secret -v %cd%/data:/app/data -v %cd%/output:/app/output springer-pipeline
    
GCS example:
  docker run -e GOOGLE_APPLICATION_CREDENTIALS=/app/creds/key.json -v %cd%/creds:/app/creds -v %cd%/data:/app/data -v %cd%/output:/app/output springer-pipeline

