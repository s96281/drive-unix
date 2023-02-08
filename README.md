# Introduction 

An index & manager of SharePoint powered by Python, Flask and Redis.  
No need to generate OneDrive API Tokens or register application in Azure.  
Built for those who can't authorize apps and don't have admin permissions.  
Completely free to host.

# Dependents

psutil redis flask chardet requests flask_caching Office365-REST-Python-Client

# Quick Start

1.	Clone the repository.

2.  Install Python3 and dependent modules.

    ```bash
    sudo apt install python3;pip install -r requirements.txt
    ```

3.	Open app.py in the project folder. And change host, port, password to your Redis server.

4.	Run with command

    ```bash
    python app.py
    ```

5.  Open http://127.0.0.1:5000/ with your browser.  
    It should be redirect to http://127.0.0.1:5000/initialization.html.  
    If it does not, you can direcly open a new tab and type the URL.

6.  Follow the tip and type in your data line by line.  
    While you finished, click "Submit" buttom.

7.  Login and Start browsing your SharePoint site in the browser!

# To-Do