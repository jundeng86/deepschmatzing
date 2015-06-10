#!/bin/bash

THEANO_FLAGS="device=gpu0" time python sequence_cnn.py -bdir /srv/data/speech/ComParE2015/eating_60fbank_8khz_aug/wav/ -f corpus/eating_challenge_nodev/ -c No_Food,Banana,Crisp,Nectarine,Haribo,Apple,Biscuit -p 500 -e 3000 -r 0.01 -m -1 -s models/final_submission/cnn_convs_500_hidden_w18_fbank60_TRANSFER_AUG --write-prediction-arff models/final_submission/cnn_500_e3000_pred_transfer_and_aug.arff -b dnn -hu 500 -bhu 1000 -l cnn --use_linear_confidence -w 18 -d 0.1,0.2,0.3,0.4,0.5,0.5,0.5,0.5 --preload-weights-from models/post_submission/voxforge_w18_fbank60.weights.partial.pickle
