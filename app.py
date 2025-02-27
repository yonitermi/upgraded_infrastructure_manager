import os
import subprocess
from flask import Flask, render_template, request, redirect, url_for, jsonify
import threading
from flask_socketio import SocketIO
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()
socketio = SocketIO(app)

winbox_path = os.getenv("WINBOX_PATH")
vpn_phonebook_path = os.getenv("VPN_PHONEBOOK_PATH")
vpn_name = os.getenv("VPN_NAME")
vpn_username = os.getenv("VPN_USERNAME")
vpn_password = os.getenv("VPN_PASSWORD")
chrome_path = os.getenv("CHROME_PATH")
default_url = os.getenv("DEFAULT_URL")
draytek_urls = os.getenv("DRAYTEK_URLS").split(',')


# Function to check if an IP is reachable
def ping_address(ip_address):
    try:
        result = subprocess.run(
            ["ping", "-n", "1", ip_address],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print(f"Ping output for {ip_address}:\n{result.stdout}")

        if "Reply from" in result.stdout and "bytes=" in result.stdout:
            return True
        elif "Destination host unreachable" in result.stdout:
            return False
        else:
            return False
    except Exception as e:
        print(f"Error while pinging {ip_address}: {e}")
        return False


import ipaddress

def is_valid_ip(ip):
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

# Connect to Winbox for MikroTik
def connect_to_winbox(address):
    try:
        subprocess.Popen([os.getenv("WINBOX_PATH"), address,
                          os.getenv("WINBOX_USERNAME"),
                          os.getenv("WINBOX_PASSWORD")])
    except Exception as e:
        print(f"Failed to open Winbox: {e}")

# Update VPN address
def update_vpn_address(vpn_name, address):
    phonebook_path = os.getenv("VPN_PHONEBOOK_PATH")
    if os.path.exists(phonebook_path):
        with open(phonebook_path, 'r') as file:
            lines = file.readlines()
        with open(phonebook_path, 'w') as file:
            in_section = False
            for line in lines:
                if line.strip().startswith(f"[{vpn_name}]"):
                    in_section = True
                elif in_section and line.strip().startswith("["):
                    in_section = False
                if in_section and line.strip().startswith("PhoneNumber="):
                    line = f"PhoneNumber={address}\n"
                file.write(line)

# Connect to VPN
def connect_to_vpn(vpn_name, username, password):
    try:
        subprocess.run(["rasdial", vpn_name, username, password], check=True)
    except subprocess.CalledProcessError:
        print("Failed to connect to VPN.")

# Open incognito browser
# Open incognito browser for a specific switch IP
def open_browser(switch_ip):
    chrome_path = os.getenv("CHROME_PATH")
    if not chrome_path:
        raise ValueError("CHROME_PATH is not set in .env")

    url = f"http://{switch_ip}"  # Use the switch's IP
    print(f"Opening incognito browser for {url}...")
    subprocess.Popen([chrome_path, "--incognito", url], stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def open_DRAYTEK_browser():
    urls = os.getenv("DRAYTEK_URLS").split(',')
    chrome_path = os.getenv("CHROME_PATH")
    for url in urls:
        print(f"Opening incognito browser for {url}...")
        subprocess.Popen([chrome_path, "--incognito", url])

def close_components():
    try:
        # Disconnect VPN
        subprocess.run(["rasdial", "/disconnect"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("VPN disconnected.")

        # Close Winbox
        subprocess.run(["taskkill", "/IM", "winbox64.exe", "/F"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("Winbox closed.")

        # Ensure rasphone is closed
        subprocess.run(["taskkill", "/IM", "rasphone.exe", "/F"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("rasphone closed.")
    except Exception as e:
        print(f"Error closing components: {e}")


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        customer_ip = request.form['customer_ip']
        if not is_valid_ip(customer_ip):
            return render_template('index.html', error="Invalid IP address format.")

        if not ping_address(customer_ip):
            return redirect(url_for('show_failure'))

        connect_to_winbox(customer_ip)
        update_vpn_address(os.getenv("VPN_NAME"), customer_ip)
        connect_to_vpn(
            os.getenv("VPN_NAME"), 
            os.getenv("VPN_USERNAME"), 
            os.getenv("VPN_PASSWORD")
        )
        return redirect(url_for('success', ip=customer_ip))
    return render_template('index.html', error=None)


@app.route('/draytek', methods=['GET', 'POST'])
def draytek():
    if request.method == 'POST':
        customer_ip = request.form['customer_ip']
        if not is_valid_ip(customer_ip):
            return render_template('index.html', error="Invalid IP address format.")

        if not ping_address(customer_ip):
            return redirect(url_for('show_failure'))

        update_vpn_address(os.getenv("VPN_NAME"), customer_ip)
        connect_to_vpn(
            os.getenv("VPN_NAME"), 
            os.getenv("VPN_USERNAME"), 
            os.getenv("VPN_PASSWORD")
        )
        open_DRAYTEK_browser()
        return redirect(url_for('success', ip=customer_ip))
    return render_template('index.html', error=None)


@app.route('/failure')
def show_failure():
    # Render the failure.html template with error context
    return render_template('failure.html', error=True)

@app.route('/success')
def success():
    ip = request.args.get('ip')
    return render_template('success.html', ip=ip)  # Load page immediately


@app.route('/scan-switches')
def scan_switches():
    def scan():
        for switch_ip in range(247, 254):
            address = f"10.0.0.{switch_ip}"
            if ping_address(address):  # Only send successful pings
                socketio.emit('switch_found', {'ip': address})
        socketio.emit('scan_complete')  # Notify frontend when done

    threading.Thread(target=scan).start()  # Run in background
    return jsonify({"status": "scanning started"}), 202


@app.route('/open-browser/<switch_ip>', methods=['POST'])
def open_browser_for_switch(switch_ip):
    try:
        print(f"Opening browser for: {switch_ip}")  # Debugging
        open_browser(switch_ip)  # Calls open_browser() with switch_ip
        return {"status": "success", "message": f"Opened browser for {switch_ip}"}, 200
    except Exception as e:
        print(f"Error: {e}")  # Debugging
        return {"status": "error", "message": str(e)}, 500



@app.route('/beecom-cloud')
def beecom():
    ip = request.args.get('ip')
    return render_template('beecom-cloud.html', ip=ip)

@app.route('/close', methods=['POST'])
def close():
    close_components()
    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(debug=True)
