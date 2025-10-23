# Use a base image with Jupyter Notebook
FROM jupyter/base-notebook

# Copy the requirements.txt file into the container
COPY requirements.txt .

# Install dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create a working directory
WORKDIR /notebooks

# Expose the default Jupyter port
EXPOSE 8888

# Command to launch Jupyter Notebook
CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''"]
