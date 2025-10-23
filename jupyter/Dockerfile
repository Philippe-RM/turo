# Utiliser une image de base avec Jupyter Notebook
FROM jupyter/base-notebook

# Installer les dépendances supplémentaires si nécessaire
# RUN pip install pandas scikit-learn seaborn

# Créer un répertoire de travail
WORKDIR /notebooks

# Exposer le port par défaut de Jupyter
EXPOSE 8888

# Commande pour lancer Jupyter Notebook
CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''"]
