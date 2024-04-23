import os
from flask import Flask, request, send_file
from urllib.request import urlretrieve

app = Flask(__name__)

username = os.environ.get("CAM_USER")
password = os.environ.get("CAM_PWD")

# Get a list of image filenames in the directory
image_dir = "data/images"
images_name = [
    "1465065360_-00240.jpg",
    "1465065780_+00180.jpg",
    "1465066800_+01200.jpg",
    "1465068000_+02400.jpg",
]
url = "https://github.com/pyronear/pyro-devops/releases/download/v0.0.1/"

if not os.path.isfile(image_dir):
    os.makedirs(image_dir, exist_ok=True)
    for name in images_name:
        print(f"Downloading images from {url + name} ...")
        urlretrieve(url + name, image_dir + "/" + name)

image_files = [
    f for f in os.listdir(image_dir) if os.path.isfile(os.path.join(image_dir, f))
]
num_images = len(image_files)
current_index = 0


@app.route("/cgi-bin/api.cgi")
def capture():
    global current_index

    # Get username and password from the URL query parameters
    user = request.args.get("user")
    passwd = request.args.get("password")

    # Check if username and password match
    if user == username and passwd == password:
        # Get the path to the current image
        image_path = os.path.join(image_dir, image_files[current_index])
        current_index = (current_index + 1) % num_images  # Move to the next image

        return send_file(image_path, mimetype="image/jpeg")
    else:
        return "Unauthorized", 401


@app.route("/health")
def health_check():
    # Return a 200 OK response if the application is healthy
    return "OK", 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        ssl_context=("data/custom_cert/cert.pem", "data/custom_cert/key.pem"),
        port=443,
        debug=True,
    )
