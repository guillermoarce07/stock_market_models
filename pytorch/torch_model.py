
""""@author: Guillermo Arce"""

# Imports
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import torch as torch
import torch.nn as nn
import math
import time
import joblib
from sklearn.metrics import mean_squared_error

# %% Constants definition

CLOSE = "close_sma"

TIME_STEPS = 100
NUMBER_PREDICTIONS = 1
CLOSE_POSITION = 0

# We have three models for three different datasets (as explained in the document):
# (1) sept_oct
# (2) oct_nov
# (3) nov_dec
MODEL = "sept_oct"

#%% Load pre-processed data

df = pd.read_csv("pytorch/data_preprocessed_"+MODEL+".csv")

df.drop(df.columns[0], axis=1, inplace=True)

#%% Convert data to time-series format, this is specific to the requirements of the model

# Splitting dataset into train and test data
n = len(df)
train_df = df[0:int(n*0.8)]
test_df = df[int(n*0.8):]

# It is not efficient to loop through the dataset while training the model. 
# So we want to transform the dataset with each row representing the historical data and the target.
# 1 - Split into X(input) and y(output)
# 2 - Transform data into time series format
def build_timeseries(mat, y_col_index):
    
    dim_0 = mat.shape[0] - TIME_STEPS
    dim_1 = mat.shape[1]

    x = np.zeros((dim_0-NUMBER_PREDICTIONS, TIME_STEPS, dim_1))
    y = np.zeros((dim_0-NUMBER_PREDICTIONS,NUMBER_PREDICTIONS))

    for i in range(dim_0-NUMBER_PREDICTIONS):
        x[i] = mat[i:TIME_STEPS+i]
        y[i] = mat[TIME_STEPS+i:TIME_STEPS+i+NUMBER_PREDICTIONS,y_col_index]

    return x, y

X_train, y_train = build_timeseries(train_df.values,CLOSE_POSITION)
X_test, y_test = build_timeseries(test_df.values,CLOSE_POSITION)

# We need to transform our data into tensors, which is the basic structure for building a Pytorch model
X_train = torch.from_numpy(X_train).type(torch.Tensor)
X_test = torch.from_numpy(X_test).type(torch.Tensor)
y_train = torch.from_numpy(y_train).type(torch.Tensor)
y_test = torch.from_numpy(y_test).type(torch.Tensor)

print("X_train shape: ", X_train.shape)
print("y_train shape: ",y_train.shape)
print("X_test shape: ",X_test.shape)
print("y_test shape: ",y_test.shape)

#%% We create the Stacked LSTM model and define its parameters

input_dim = 7
hidden_dim = 100
num_layers = 3
output_dim = NUMBER_PREDICTIONS

# We define our model as a class
class LSTM(nn.Module):
    def __init__(self, input_dim, hidden_dim, num_layers, output_dim):
        super(LSTM, self).__init__()
        # Hidden layer dimensions
        self.hidden_dim = hidden_dim
        # Number of hidden layers
        self.num_layers = num_layers
        # Building stacked LSTM
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True) # batch_first=True causes input/output tensors to be of shape (batch_dim, seq_dim, feature_dim)
        # Linear layer
        self.fc = nn.Linear(hidden_dim, output_dim)

    def forward(self, x):        
        # Initialize hidden state with zeros
        h_0 = torch.zeros(self.num_layers, x.size(0), self.hidden_dim)
        
        # Initialize cell state
        c_0 = torch.zeros(self.num_layers, x.size(0), self.hidden_dim)
        
        output, (h_n, c_n) = self.lstm(x, (h_0, c_0))
        
        #Linear layer process the last time-step data
        output = self.fc(output[:, -1, :]) 
        
        return output
    

model = LSTM(input_dim=input_dim, hidden_dim=hidden_dim,
             num_layers=num_layers,output_dim=output_dim)

#Loss function -> MSE
loss_fn = torch.nn.MSELoss(reduction='mean')

#Optimizer -> ADAM with learning rate = 0.001
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

print(model)

for i in range(len(list(model.parameters()))):
    print(list(model.parameters())[i].size())
#%% Start the training of the model (not recommended if you are under 16-32GB of RAM). The preferred option is to load one of the 
#   existing models (see next block)

epoch_time = time.time()
start_time = time.time()

num_epochs=250
hist = np.zeros(num_epochs)
val = np.zeros(num_epochs)

for t in range(num_epochs):
    
    # Zero out gradient, else they will accumulate between epochs
    optimizer.zero_grad()
    
    # Forward pass
    y_train_pred = model(X_train)
    
    # Loss function calculation
    loss = loss_fn(y_train_pred, y_train)
    hist[t] = loss.item()/X_train.shape[0]

    # Backward pass (gradient calculation)
    loss.backward()

    # Update parameters (optimization)
    optimizer.step()          

    #Validation
    val_pred = model(X_test)
    val_loss = loss_fn(val_pred,y_test)
    val[t]=val_loss.item()/X_test.shape[0]
    
    if(t%5==0):
        print("TRAIN ERROR: ",hist[t])
        print("VAL ERROR: ",val[t])
        print("EPOCH ",t, " TIME: ", time.time()-epoch_time)
        epoch_time = time.time()
 	
training_time = time.time()-start_time
print("Training time: {}".format(training_time))

#Save the model
torch.save(model.state_dict(), "model.pth") 
np.savetxt("validation.csv", val, delimiter=",")
np.savetxt("loss.csv", hist, delimiter=",")

#%%Load a model, if desired (remember to create it first, with the block starting in line 74)

model.load_state_dict(torch.load("pytorch/trained_models/"+MODEL+"/model.pth"))
model.eval()

#%% Function to make predictions
def make_predictions(plot_extension, data):
    all_predictions = []
    for i in range(0,plot_extension,NUMBER_PREDICTIONS):
        
        input_data = data[i].reshape(-1,data.shape[1],data.shape[2]) 

        prediction=model(input_data)
        
        for j in range(NUMBER_PREDICTIONS):
            all_predictions.append(prediction[0,j])
            
    return all_predictions
    
#%% Function to calculate direction prediction accuraccy

#   The direction accuraccy is calculated by 
#   comparing the last price value predicted with the last price value of the **previous prediction**. 
#   So, in order to calculate the direction of a prediction, we would need to calculate the previous 
#   prediction and compare those values. Otherwise, if we compare the predicted price with the real price
#   in order to get the direction of the prediction, we would be harming the capacity of the model of 
#   predicting the direction; as the error of the exact price value prediction would be affecting it.
#   To sum up, the idea of working in this way is not to mix the (1) capacity of the model of predicting 
#   the direction (that may be easier to predict and with less error) and the (2) capacity of the model 
#   of predicting the exact price (more difficult to calculate and with more error).
    
#Example:
# Predicted prices in batches of NUMBER_PREDICTIONS = 3:
# 54.6 54.3 54.2(A) | 57.8 57.5 57.4(B) | 57.9 60.1 60.2(C) | 57.8 57.5 57.4(D)
# Number A (54.2) is compared to number B (57.4) in order to get if the prediction direction has been
# that the price will increase (UP) or decrease (DOWN); in this case the price has raised (UP)
# In the same way, (B) would be compared with (C), (C) with (D)...
def direction_accuraccy(predictions,real):    
    results_pred = []
    results_real = []
    for i in range(NUMBER_PREDICTIONS-1, len(predictions)-1, NUMBER_PREDICTIONS):
        pred_first_price = predictions[i]
        pred_last_price = predictions[i+NUMBER_PREDICTIONS]
        up = pred_first_price<pred_last_price
        results_pred.append(up)
        
        real_first_price = real[i]
        real_last_price= real[i+NUMBER_PREDICTIONS]
        up = real_first_price<real_last_price
        results_real.append(up)
    
    #Count the errors in direction prediction
    direction_errors = 0
    for i in range (len(results_pred)):
        if(results_pred[i]!=results_real[i]):
            direction_errors+=1  
            
    print("Direction Errors: ", direction_errors,"/",len(results_pred))
    print("Direction Accuraccy: ", (len(results_pred)-direction_errors)*100/len(results_pred), "%")
    
#%% Execution of predictions until the selected extension, also if train or test data is used should be specified

#With current pre-processed data, plot_extension value could be up to (be careful with the RAM, I recommend using smaller values, like 1000):
    # For dataset sept_oct: 3430 (for test data) and 14040 (for train data) 
    # For dataset oct_nov: 3690 (for test data) and 15080 (for train data)
    # For dataset nov_dec: 3380 (for test data) and 13850 (for train data)

plot_extension = 500
test_data = True

print("Making predictions, this may take a while...")

if(test_data):
    predictions = make_predictions(plot_extension, X_test)
else:
    predictions = make_predictions(plot_extension, X_train)

print("Done! Please, re-scale and plot with the following code blocks")

#%% Re-scale prediction
close_scaler = joblib.load("pytorch/close_scaler_"+MODEL+".pkl") 
predictions = close_scaler.inverse_transform(np.asarray(predictions).reshape(1, -1))[0]

#%% Calculate RMSE and direction accuracy; also plot

#(1) Getting original prices
if(test_data):
    aux = (test_df[CLOSE]).to_numpy()
    real_prices = aux[TIME_STEPS:plot_extension+TIME_STEPS]
else:
    aux = (train_df[CLOSE]).to_numpy()
    real_prices = aux[TIME_STEPS:plot_extension+TIME_STEPS]
    
#(2) Re-scale original prices
real_prices = close_scaler.inverse_transform(np.asarray(real_prices).reshape(1, -1))[0]
    
#(3) Calculate RMSE
error = math.sqrt(mean_squared_error(real_prices,predictions))
print ("RMSE: ",error)

#(4) Plot
plt.plot(predictions)
plt.plot(real_prices)
plt.legend(['Prediction', 'Real'], loc='best')
plt.xlabel("Minutes")
plt.ylabel("Price")
plt.show()

#(5) Calculate direction accuraccy of predictions
direction_accuraccy(predictions, real_prices)
