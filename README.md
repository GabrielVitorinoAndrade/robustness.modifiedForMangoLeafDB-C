# Creating MangoLeafDB-C

This project is a modification of robustness (https://github.com/hendrycks/robustness).

My project is to create MangoLeafDB-C, which is the corrupted MangoLeafDB, with the purpose of benchmarking CNNs that classify diseases in mango leaves. This research was published in an article by my research group "EASY - Center for Research in Engineering and Systems" at UFAL. The name of our group within "EASY" is "Edge ML".

The research title is: "From Code to Field: Evaluating the Robustness of Convolutional Neural Networks for Disease Diagnosis in Mango Leaves"

Dataset - MangoLeaf-DB: https://www.kaggle.com/datasets/aryashah2k/mango-leaf-disease-dataset/data

# Modifications to the original project
I forked the original repository and made modifications to the following path ImageNet-C/create_c/make_imagenet_c.py. Where modifications were necessary to make all output images 224x224 and modifications to the save directory, all with the aim of creating MangoLeafDB-C.
