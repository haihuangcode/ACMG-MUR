import torch
import torch.nn as nn


class Cross_CPC(nn.Module):
    def __init__(self, embedding_dim, hidden_dim, context_dim, num_layers, n_prediction_steps=1, min_start_steps=1):
        super(Cross_CPC, self).__init__()
        self.embedding_dim = embedding_dim
        self.hidden_dim = hidden_dim
        self.context_dim = context_dim
        self.num_layers = num_layers
        self.n_prediction_steps = n_prediction_steps
        self.min_start_steps = min_start_steps
        self.softmax  = nn.Softmax()
        self.lsoftmax = nn.LogSoftmax()
        
        # Autoregressive LSTM network for video
        self.video_ar_lstm = nn.LSTM(embedding_dim, context_dim, num_layers, batch_first=True)
        
        # Autoregressive LSTM network for audio
        self.audio_ar_lstm = nn.LSTM(embedding_dim, context_dim, num_layers, batch_first=True)
        
        # Predictor network for video
        self.video_predictors = nn.ModuleList([
            nn.Linear(context_dim, embedding_dim) for _ in range(n_prediction_steps)
        ])
        
        # Predictor network for audio
        self.audio_predictors = nn.ModuleList([
            nn.Linear(context_dim, embedding_dim) for _ in range(n_prediction_steps)
        ])
    
    """
    video_forward_seq took the first t_samples+1 samples [0:t_samples].
    video_encode_samples took the samples [t_samples+1:t_samples+self.n_prediction_steps] as true future results.
    The LSTM utilized video_forward_seq to obtain video_context,
    then used video_predictors to predict video_pred.
    Calculate NCE between pred and encode_samples.
    """
    def forward(self, video_vq, audio_vq):
        batch_dim, time_length, _ = video_vq.shape# [batch_dim, time_length, embedding_dim] e.g.[80, 10, 256]
        # closedOpen
        # Choose any number from [3, 8) as a starting point, then predict the next two digits. Therefore, forward_seq has a minimum length of 4 (starting from 0).
        t_samples = (torch.randint(time_length - self.n_prediction_steps - self.min_start_steps, size=(1,)) + self.min_start_steps).long() # randomly pick time stamps
        # losses = list()
        nce = 0 # average over timestep and batch
        video_encode_samples = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = video_vq.device).double() # e.g. size 5*80*256
        audio_encode_samples = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = audio_vq.device).double() # e.g. size 5*80*256
        for i in range(1, self.n_prediction_steps+1):# closedOpen
            video_encode_samples[i-1] = video_vq[:,t_samples+i,:].reshape(batch_dim,self.embedding_dim) # z_tk e.g. size 80*256
            audio_encode_samples[i-1] = audio_vq[:,t_samples+i,:].reshape(batch_dim,self.embedding_dim) # z_tk e.g. size 80*256
        video_forward_seq = video_vq[:,:t_samples+1,:] # e.g. size 80*t_samples*256
        audio_forward_seq = audio_vq[:,:t_samples+1,:] # e.g. size 80*t_samples*256
        # Autoregressive LSTM for video
        video_hidden = (torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = video_vq.device).float(),
                  torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = video_vq.device).float())
        video_context, video_hidden = self.video_ar_lstm(video_forward_seq, video_hidden)
        
        # Autoregressive LSTM for audio
        audio_hidden = (torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = audio_vq.device).float(),
                  torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = audio_vq.device).float())
        audio_context, audio_hidden = self.audio_ar_lstm(audio_forward_seq, audio_hidden)
        
        video_context = video_context[:,t_samples,:].reshape(batch_dim,self.context_dim) # c_t e.g. size 80*512
        audio_context = audio_context[:,t_samples,:].reshape(batch_dim,self.context_dim) # c_t e.g. size 80*512
        
        video_pred = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = video_vq.device).double() # e.g. size 5*80*256
        audio_pred = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = audio_vq.device).double() # e.g. size 5*80*256
        for i in range(0, self.n_prediction_steps):
            video_linear = self.video_predictors[i]
            video_pred[i] = video_linear(video_context) #e.g. size 80*512 -> 80*256
            audio_linear = self.audio_predictors[i]
            audio_pred[i] = audio_linear(audio_context) #e.g. size 80*512 -> 80*256
        for i in range(0, self.n_prediction_steps):
            total1 = torch.mm(video_encode_samples[i], torch.transpose(audio_pred[i],0,1)) # e.g. size 80*80
            total2 = torch.mm(audio_encode_samples[i], torch.transpose(video_pred[i],0,1)) # e.g. size 80*80
            total3 = torch.mm(video_encode_samples[i], torch.transpose(video_pred[i],0,1)) # e.g. size 80*80
            total4 = torch.mm(audio_encode_samples[i], torch.transpose(audio_pred[i],0,1)) # e.g. size 80*80
            correct1 = torch.sum(torch.eq(torch.argmax(self.softmax(total1), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct2 = torch.sum(torch.eq(torch.argmax(self.softmax(total2), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct3 = torch.sum(torch.eq(torch.argmax(self.softmax(total3), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct4 = torch.sum(torch.eq(torch.argmax(self.softmax(total4), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            w1 = 1.0
            w2 = 1.0
            # Slightly computing self nce for each modality can provide a direction to align different modalities.
            w3 = 0.1
            w4 = 0.1
            nce += w1 * torch.sum(torch.diag(self.lsoftmax(total1))) # nce is a tensor
            nce += w2 * torch.sum(torch.diag(self.lsoftmax(total2))) # nce is a tensor
            nce += w3 * torch.sum(torch.diag(self.lsoftmax(total3))) # nce is a tensor
            nce += w4 * torch.sum(torch.diag(self.lsoftmax(total4))) # nce is a tensor
            
        nce /= -1.*batch_dim*self.n_prediction_steps
        accuracy1 = 1.*correct1/batch_dim
        accuracy2 = 1.*correct2/batch_dim
        accuracy3 = 1.*correct3/batch_dim
        accuracy4 = 1.*correct4/batch_dim
        return accuracy1, accuracy2, accuracy3, accuracy4, nce
    

class Cross_CPC_AVT(nn.Module):
    def __init__(self, embedding_dim, hidden_dim, context_dim, num_layers, n_prediction_steps=1, min_start_steps=1):
        super(Cross_CPC_AVT, self).__init__()
        self.embedding_dim = embedding_dim
        self.hidden_dim = hidden_dim
        self.context_dim = context_dim
        self.num_layers = num_layers
        self.n_prediction_steps = n_prediction_steps
        self.min_start_steps = min_start_steps
        self.softmax  = nn.Softmax()
        self.lsoftmax = nn.LogSoftmax()
        
        # Autoregressive LSTM network for video
        self.video_ar_lstm = nn.LSTM(embedding_dim, context_dim, num_layers, batch_first=True)
        
        # Autoregressive LSTM network for audio
        self.audio_ar_lstm = nn.LSTM(embedding_dim, context_dim, num_layers, batch_first=True)
        
        # Autoregressive LSTM network for audio
        self.text_ar_lstm = nn.LSTM(embedding_dim, context_dim, num_layers, batch_first=True)
        
        # Predictor network for video
        self.video_predictors = nn.ModuleList([
            nn.Linear(context_dim, embedding_dim) for _ in range(n_prediction_steps)
        ])
        
        # Predictor network for audio
        self.audio_predictors = nn.ModuleList([
            nn.Linear(context_dim, embedding_dim) for _ in range(n_prediction_steps)
        ])
        
        # Predictor network for text
        self.text_predictors = nn.ModuleList([
            nn.Linear(context_dim, embedding_dim) for _ in range(n_prediction_steps)
        ])
    
    """
    video_forward_seq took the first t_samples+1 samples [0:t_samples].
    video_encode_samples took the samples [t_samples+1:t_samples+self.n_prediction_steps] as true future results.
    The LSTM utilized video_forward_seq to obtain video_context,
    then used video_predictors to predict video_pred.
    Calculate NCE between pred and encode_samples.
    """
    def forward(self, audio_vq, video_vq, text_vq):
        batch_dim, time_length, _ = video_vq.shape# [batch_dim, time_length, embedding_dim] e.g.[80, 10, 256]

        t_samples = (torch.randint(time_length - self.n_prediction_steps - self.min_start_steps, size=(1,)) + self.min_start_steps).long() # randomly pick time stamps
        # losses = list()
        nce = 0 # average over timestep and batch
        video_encode_samples = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = video_vq.device).double() # e.g. size 5*80*256
        audio_encode_samples = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = audio_vq.device).double() # e.g. size 5*80*256
        text_encode_samples = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = text_vq.device).double() # e.g. size 5*80*256
        for i in range(1, self.n_prediction_steps+1):
            video_encode_samples[i-1] = video_vq[:,t_samples+i,:].reshape(batch_dim,self.embedding_dim) # z_tk e.g. size 80*256
            audio_encode_samples[i-1] = audio_vq[:,t_samples+i,:].reshape(batch_dim,self.embedding_dim) # z_tk e.g. size 80*256
            text_encode_samples[i-1] = text_vq[:,t_samples+i,:].reshape(batch_dim,self.embedding_dim) # z_tk e.g. size 80*256
        video_forward_seq = video_vq[:,:t_samples+1,:] # e.g. size 80*t_samples*256
        audio_forward_seq = audio_vq[:,:t_samples+1,:] # e.g. size 80*t_samples*256
        text_forward_seq = text_vq[:,:t_samples+1,:] # e.g. size 80*t_samples*256
        # Autoregressive LSTM for video
        video_hidden = (torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = video_vq.device).double(),
                  torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = video_vq.device).double())
        video_context, video_hidden = self.video_ar_lstm(video_forward_seq, video_hidden)
        
        # Autoregressive LSTM for audio
        audio_hidden = (torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = audio_vq.device).double(),
                  torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = audio_vq.device).double())
        audio_context, audio_hidden = self.audio_ar_lstm(audio_forward_seq, audio_hidden)
        
        # Autoregressive LSTM for text
        text_hidden = (torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = text_vq.device).double(),
                  torch.zeros(self.num_layers, batch_dim, self.hidden_dim, device = text_vq.device).double())
        text_context, text_hidden = self.text_ar_lstm(text_forward_seq, text_hidden)
        
        video_context = video_context[:,t_samples,:].reshape(batch_dim,self.context_dim) # c_t e.g. size 80*512
        audio_context = audio_context[:,t_samples,:].reshape(batch_dim,self.context_dim) # c_t e.g. size 80*512
        text_context = text_context[:,t_samples,:].reshape(batch_dim,self.context_dim) # c_t e.g. size 80*512
        
        video_pred = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = video_vq.device).double() # e.g. size 5*80*256
        audio_pred = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = audio_vq.device).double() # e.g. size 5*80*256
        text_pred = torch.empty((self.n_prediction_steps,batch_dim,self.embedding_dim), device = audio_vq.device).double() # e.g. size 5*80*256
        
        for i in range(0, self.n_prediction_steps):
            video_linear = self.video_predictors[i]
            video_pred[i] = video_linear(video_context) #e.g. size 80*512 -> 80*256
            audio_linear = self.audio_predictors[i]
            audio_pred[i] = audio_linear(audio_context) #e.g. size 80*512 -> 80*256
            text_linear = self.text_predictors[i]
            text_pred[i] = text_linear(text_context) #e.g. size 80*512 -> 80*256
        for i in range(0, self.n_prediction_steps):
            total1 = torch.mm(audio_encode_samples[i], torch.transpose(video_pred[i],0,1)) # e.g. size 80*80
            total2 = torch.mm(audio_encode_samples[i], torch.transpose(text_pred[i],0,1)) # e.g. size 80*80
            total3 = torch.mm(video_encode_samples[i], torch.transpose(text_pred[i],0,1)) # e.g. size 80*80
            total4 = torch.mm(video_encode_samples[i], torch.transpose(audio_pred[i],0,1)) # e.g. size 80*80
            total5 = torch.mm(text_encode_samples[i], torch.transpose(audio_pred[i],0,1)) # e.g. size 80*80
            total6 = torch.mm(text_encode_samples[i], torch.transpose(video_pred[i],0,1)) # e.g. size 80*80
            total7 = torch.mm(audio_encode_samples[i], torch.transpose(audio_pred[i],0,1)) # e.g. size 80*80
            total8 = torch.mm(video_encode_samples[i], torch.transpose(video_pred[i],0,1)) # e.g. size 80*80
            total9 = torch.mm(text_encode_samples[i], torch.transpose(text_pred[i],0,1)) # e.g. size 80*80
            correct1 = torch.sum(torch.eq(torch.argmax(self.softmax(total1), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct2 = torch.sum(torch.eq(torch.argmax(self.softmax(total2), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct3 = torch.sum(torch.eq(torch.argmax(self.softmax(total3), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct4 = torch.sum(torch.eq(torch.argmax(self.softmax(total4), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct5 = torch.sum(torch.eq(torch.argmax(self.softmax(total5), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct6 = torch.sum(torch.eq(torch.argmax(self.softmax(total6), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct7 = torch.sum(torch.eq(torch.argmax(self.softmax(total7), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct8 = torch.sum(torch.eq(torch.argmax(self.softmax(total8), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            correct9 = torch.sum(torch.eq(torch.argmax(self.softmax(total9), dim=0), torch.arange(0, batch_dim, device = video_vq.device))) # correct is a tensor
            w1 = 1.0
            w2 = 1.0
            w3 = 1.0
            w4 = 1.0
            w5 = 1.0
            w6 = 1.0
            # Slightly computing self nce for each modality can provide a direction to align different modalities.
            w7 = 0.1
            w8 = 0.1
            w9 = 0.1
            nce += w1 * torch.sum(torch.diag(self.lsoftmax(total1))) # nce is a tensor
            nce += w2 * torch.sum(torch.diag(self.lsoftmax(total2))) # nce is a tensor
            nce += w3 * torch.sum(torch.diag(self.lsoftmax(total3))) # nce is a tensor
            nce += w4 * torch.sum(torch.diag(self.lsoftmax(total4))) # nce is a tensor
            nce += w5 * torch.sum(torch.diag(self.lsoftmax(total5))) # nce is a tensor
            nce += w6 * torch.sum(torch.diag(self.lsoftmax(total6))) # nce is a tensor
            nce += w7 * torch.sum(torch.diag(self.lsoftmax(total7))) # nce is a tensor
            nce += w8 * torch.sum(torch.diag(self.lsoftmax(total8))) # nce is a tensor
            nce += w9 * torch.sum(torch.diag(self.lsoftmax(total9))) # nce is a tensor
            
        nce /= -1.*batch_dim*self.n_prediction_steps
        accuracy1 = 1.*correct1/batch_dim
        accuracy2 = 1.*correct2/batch_dim
        accuracy3 = 1.*correct3/batch_dim
        accuracy4 = 1.*correct4/batch_dim
        accuracy5 = 1.*correct5/batch_dim
        accuracy6 = 1.*correct6/batch_dim
        accuracy7 = 1.*correct7/batch_dim
        accuracy8 = 1.*correct8/batch_dim
        accuracy9 = 1.*correct9/batch_dim
        return accuracy1, accuracy2, accuracy3, accuracy4, accuracy5, accuracy6, accuracy7, accuracy8, accuracy9, nce