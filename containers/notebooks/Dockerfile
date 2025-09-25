# Use an official Python runtime as a parent image
FROM python:3.8

# Set the working directory to /app
WORKDIR /app

# Copy the requirements into the container at /app
COPY ./requirements.txt /app/requirements.txt

# Install Jupyter Notebook any needed packages specified in requirements.txt
RUN pip install --no-cache-dir jupyter==1.1.1 &&\
 pip install --no-cache-dir -r requirements.txt

# Make port 8888 available to the world outside this container
EXPOSE 8888

# Define environment variable
ENV NAME=pyro-envdev

# Run Jupyter Notebook when the container launches
CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''"]
