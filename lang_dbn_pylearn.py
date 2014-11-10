from nolearn.dbn import DBN
import argparse
import numpy as np
from sklearn.cross_validation import train_test_split
from sklearn.metrics import classification_report
from sklearn.metrics import accuracy_score
from sklearn.metrics import confusion_matrix
from sklearn.preprocessing import StandardScaler

from sklearn.decomposition import RandomizedPCA

import sklearn
import itertools

from pylab import *

from utils import unspeech_utils,ZCA,mean_substract#,pylearnkit

from feature_gen import energy,windowed_fbank

import scipy.stats
from scipy.stats import itemfreq

from sklearn.cross_validation import StratifiedShuffleSplit

import cPickle as pickle

def serialize(data, filename):
    f = open(filename,"wb")
    pickle.dump(data, f, protocol=2)
    f.close()

def load(filename):
    f = open(filename,"rb")
    p = pickle.load(f)
    f.close()
    return(p)

#load and construct feature vectors for a single logspec file id
def loadIdFeat(myid,dtype, window_size, step_size,stride,energy_filter=1.2):
    logspec_features = np.load(myid+'.logspec.npy')
    if(logspec_features.dtype != dtype):
        logspec_features = logspec_features.astype(dtype, copy=False)

    logspec_features_filtered = energy.filterSpec(logspec_features,energy_filter)
    feat = windowed_fbank.generate_feat(logspec_features_filtered,window_size,step_size,stride)
    return feat

#load specgrams and generate windowed feature vectors
def loadTrainData(ids,classes,window_size,step_size,stride):
    
    #iterate through all files and find out the space needed to store all data in memory
    required_shape = [0,0]
    for myid in ids:
        #do not load array into memory yet
        #logspec_features_disk = np.load(myid+'.logspec.npy',mmap_mode='r')
        #feat_gen_shape = windowed_fbank.len_feat(logspec_features_disk.shape, window_size,step_size,stride)
        feat_gen_shape = loadIdFeat(myid,'float32',window_size,step_size,stride).shape
        required_shape[1] = feat_gen_shape[1]
        required_shape[0] += feat_gen_shape[0]

    # explicitly set X data to 32bit resolution and y data to 8 bit (256 possible languages / classes)
    X_data = np.zeros(required_shape,dtype='float32')
    y_data = np.zeros(required_shape[0],dtype='uint8')

    #now we will load the npy files into memory and generate features
    pos = 0
    for myid,myclass in itertools.izip(ids,classes):
            feat = loadIdFeat(myid,'float32',window_size,step_size,stride)
            feat_len = feat.shape[0]
            feat_dim = feat.shape[1]
            y_data[pos:pos+feat_len] = myclass
            X_data[pos:pos+feat_len] = feat 

            pos += feat_len

    return X_data,y_data

class MyModel:
    def __init__(self, window_sizes,step_sizes,strides,lang2num,pretrainepochs,epochs,use_pca=True,pca_whiten=False,pca_components=100,learn_rates=0.001,learn_rates_pretrain=0.00001,minibatch_size=200,hid_layer_units=1000,dropouts=0,random_state=0):
        self._scalers = []
        self._dbns = []
        self._pcas = []
        #self.all_ids = all_ids
        #self.classes = classes
        self.window_sizes = window_sizes
        self.step_sizes = step_sizes
        self.strides = strides
        self.pca_components = pca_components
        self.lang2num = lang2num
        self.pretrainepochs = pretrainepochs
        self.epochs = epochs
        self._no_langs = len(langs)
        self.learn_rates = learn_rates
        self.learn_rates_pretrain = learn_rates_pretrain
        self.minibatch_size = minibatch_size
        self.hid_layer_units = hid_layer_units
        self.dropouts = dropouts
        self.random_state = random_state
        self.use_pca = use_pca
        self.pca_whiten = pca_whiten
        self.deep_learner = 'nolearn'

    #Prepare coprpus and train dbn classifier
    def trainClassifier(self,all_ids,classes,window_size,step_size,stride,pretrainepochs,epochs,learn_rates=0.001,learn_rates_pretrain=0.00001,minibatch_size=256,hid_layer_units=1000,dropouts=0,random_state=0):
        y_all = np.asarray(classes)
        #sss = StratifiedShuffleSplit(y_all, 1, test_size=0.01, random_state=random_state)
        #train_index, test_index = iter(sss).next()

        #X_ids_train, X_ids_test = [all_ids[index] for index in train_index], [all_ids[index] for index in test_index]
        #y_train_flat, y_test_flat = y_all[train_index], y_all[test_index]

        #The vectors in X and corresponding classes y are now only portions of the signal of an id
        #X_train,y_train = loadTrainData(X_ids_train, y_train_flat, window_size, step_size,stride)

        X_train,y_train = loadTrainData(all_ids, y_all, window_size, step_size,stride)

        #Scale mean of all training vectors
        #std_scale = StandardScaler(copy=False, with_mean=True, with_std=False).fit(X_train)
        std_scale = mean_substract.MeanNormalize(copy=False).fit(X_train)
        X_train = std_scale.transform(X_train)

        if self.use_pca:
            pca = RandomizedPCA(n_components=self.pca_components, copy=False,
                           whiten=self.pca_whiten, random_state=random_state)
            #Pca fit
            pca.fit(X_train)
            X_train = pca.transform(X_train)
        else:
            pca = None

        unspeech_utils.shuffle_in_unison(X_train,y_train)

        print 'Done loading data, trainsize:', len(all_ids)
        #print 'testsize:', len(X_ids_test)

        print 'Distribution of classes in train data:'
        print itemfreq(y_train),self._no_langs
        #print 'Distribution of classes in test data:'
        #print itemfreq(y_test_flat)

        if(X_train.dtype != 'float32'):
            print 'Warning, training data was not float32: ', X_train.dtype
            X_train = X_train.astype('float32', copy=False)

        if self.deep_learner=='pylearn2':
            clf = pylearnkit.MaxoutClassifier(
                    num_pieces = 4,
                    num_units = (hid_layer_units,hid_layer_units,hid_layer_units),
                    learning_rate = learn_rates,
                    num_classes = self._no_langs,
                    batch_size=minibatch_size,
                    epochs=epochs
                    )
        else:
            n_layers = 4
            clf = DBN([X_train.shape[1], hid_layer_units, hid_layer_units, hid_layer_units/10, hid_layer_units, len(langs)],
                    dropouts=[0.2] + [0.5] * n_layers,
                    learn_rates=learn_rates,
                    learn_rates_pretrain=learn_rates_pretrain,
                    minibatch_size=minibatch_size,
                    #learn_rate_decays=0.9,
                    epochs_pretrain=pretrainepochs,
                    epochs=args.epochs,
                    momentum= 0.9,
                    real_valued_vis=True,
                    use_re_lu=True,
                    verbose=1)
        
        print 'fitting dbn...'
        clf.fit(X_train, y_train)

        print 'done!'

        return std_scale,pca,clf

    def fit(self,all_ids,classes):
        self._dbns,self._scalers,self.X_ids_train,self.X_ids_test,self.y_test_flat = [],[],None,None,None

        for i in xrange(no_classifiers):
            print 'Train #',i,' dbn classifier with window_size:',window_sizes[i],'step_size=',step_sizes[i]
            std_scale,pca,clf = self.trainClassifier(all_ids,classes,self.window_sizes[i],self.step_sizes[i],self.strides[i],self.pretrainepochs,self.epochs,hid_layer_units=self.hid_layer_units,random_state=self.random_state)
            self._dbns.append(clf)
            self._scalers.append(std_scale)
            self._pcas.append(pca)
    
    #fuse frame probabiltites, defaults to geometric mean
    def fuse_op(self,frame_proba, op=scipy.stats.gmean, normalize=True):
        no_classes = frame_proba.shape[0]
        
        #nothing to fuse
        if frame_proba.shape[1] < 2:
            return frame_proba

        fused_proba = op(frame_proba)
        
        if len(fused_proba) != no_classes:
            fused_proba.resize((no_classes,))
        
        if normalize:
            return unspeech_utils.normalize_unitlength(fused_proba)
        else:
            return fused_proba

    def inspect_predict(self,utterance_id):
        clf,std_scale,pca,window_size,step_size,stride = self._dbns[0],self._scalers[0],self._pcas[0],self.window_sizes[0],self.step_sizes[0],self.strides[0]
        
        logspec_features = np.load(utterance_id+'.logspec.npy')
        
        utterance = loadIdFeat(utterance_id,'float32',window_size, step_size, stride)
        
        subplot(411)
        imshow(logspec_features.T, aspect='auto', interpolation='nearest')

        subplot(412)
        imshow(utterance.T, aspect='auto', interpolation='nearest')
        
        utterance = std_scale.transform(utterance)
        if self.use_pca:
            print 'Using pca transform'
            utterance = pca.transform(utterance)

        subplot(413)
        imshow(utterance.T, aspect='auto', interpolation='nearest')

        print 'calling classifier',utterance.dtype,utterance.shape
        frame_proba = clf.predict_proba(utterance)

        subplot(414)
        imshow(frame_proba.T, aspect='auto', interpolation='nearest')

        show()

    def predict_utterance(self,utterance_id):
        voting = []
        multi_pred = []
        for clf,std_scale,pca,window_size,step_size,stride in itertools.izip(self._dbns,self._scalers,self._pcas,self.window_sizes,self.step_sizes,self.strides):
            utterance = loadIdFeat(utterance_id,'float32',window_size, step_size, stride)
            utterance = std_scale.transform(utterance)
            if self.use_pca:
                utterance = pca.transform(utterance)

            if(utterance.dtype != 'float32'):
                print 'Warning, training data was not float32: ', utterance.dtype
                utterance = utterance.astype('float32', copy=False)

            #hard decision per frame, agg with majority voting
            #local_pred_all = clf.predict(utterance)
            #local_vote = np.bincount(local_pred_all)          
            #local_pred = np.argmax(local_vote)
            print 'calling classifier',utterance.dtype,utterance.shape
            #soft desision, agg of probabilities
            frame_proba = clf.predict_proba(utterance)
            
            local_vote = self.fuse_op(frame_proba,op=scipy.stats.gmean)
            #local_vote1 = self.fuse_op(frame_proba,op=np.bincount)
            local_vote2 = self.fuse_op(frame_proba,op=np.add.reduce)
            local_vote3 = self.fuse_op(frame_proba,op=np.multiply.reduce)
            local_vote4 = self.fuse_op(frame_proba,op=np.maximum.reduce)

            voting += [local_vote,local_vote2,local_vote3,local_vote4]
            multi_pred += [np.argmax(local_vote),np.argmax(local_vote2),np.argmax(local_vote3),np.argmax(local_vote4)]
        
        #geometric mean of classifiers, majority voting on utterance
        pred = np.argmax(np.add.reduce(voting))
        return pred,multi_pred 

'''generic classification report for real_classes vs. predicted_classes'''
def print_classificationreport(real_classes, predicted_classes):
    print "Accuracy:", accuracy_score(real_classes, predicted_classes)
    print "Classification report:"
    print classification_report(real_classes, predicted_classes)
    print "Confusion matrix:\n%s" % confusion_matrix(real_classes, predicted_classes)

'''return the given set, with classes and name (usually train, dev, or test), as tuple of ids (list) and matching classes (list)'''
def load_set(classes,name,max_samples,class2num):
    set_ids = []
    set_classes = [] 
    
    for myclass in classes:
        ids = unspeech_utils.loadIdFile(args.filelists+name+'_'+myclass+'.txt',basedir=args.basedir)
        for myid in ids[:max_samples]:
            set_ids.append(myid)
            set_classes.append(class2num[myclass])
    return set_ids,set_classes

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Calculate FBANK features (=logarithmic mel frequency filter banks) for all supplied files in file list (txt).')
    parser.add_argument('-f', '--filelists-dir', dest="filelists", help='file list basedir', default='corpus/voxforge/', type=str)
    parser.add_argument('-v', dest='verbose', help='verbose output', action='store_true', default=False)
    parser.add_argument('-c', '--classes', dest='classes', help='comma seperated list of classes',type=str,default='de,fr')
    parser.add_argument('-m', '--max', dest='max_samples', help='max utterance samples per language',type=int,default=-1)
    parser.add_argument('-b', '--basedir',dest='basedir', help='base dir of all files, should end with /', default = './', type=str)
    parser.add_argument('-e', '--epochs',dest='epochs', help='number of supervised finetuning epochs', default = 20, type=int)
    parser.add_argument('-p', '--pretrain-epochs',dest='pretrainepochs', help='number of unsupervised epochs', default = 10, type=int)
    parser.add_argument('-s', '--save-model',dest='modelfilename', help='store trained model to this filename, if specified', default = '', type=str)
    parser.add_argument('-d', '--dropouts',dest='dropouts', help='dropout param in dbn', default = 0.0, type=float)
    parser.add_argument('-u', '--hidden-layer-units',dest='hiddenlayerunits', help='dropout param in dbn', default = 1000, type=int)
    parser.add_argument('-l', '--learnrate',dest='learnrate', help='learning rate', default = 0.01, type=float)
    parser.add_argument('--pca', dest='use_pca', help='pca reduction of feature space', action='store_true', default=False)
    parser.add_argument('--pca-whiten', dest='pca_whiten', help='pca whiten (decorellate) features', action='store_true', default=False)

    window_sizes = [21] #[15,26]#[11,21]
    step_sizes = [3] #[10,17]#[7,15]
    strides = [7]

    no_classifiers = len(window_sizes)

    hid_layer_units = 1000

    args = parser.parse_args()

    langs = (args.classes).split(',')
    lang2num = {}
    for i,lang in enumerate(langs):
        lang2num[lang] = i
    
    no_langs = len(langs)

    all_ids, classes = load_set(langs,'train',args.max_samples,lang2num)
    dev_ids, dev_classes = load_set(langs,'dev',args.max_samples,lang2num)

    model = MyModel(window_sizes,step_sizes,strides,lang2num,use_pca=args.use_pca,pca_whiten=args.pca_whiten,pretrainepochs=args.pretrainepochs,epochs=args.epochs,dropouts=args.dropouts,hid_layer_units=args.hiddenlayerunits, learn_rates=args.learnrate)
    model.fit(all_ids,classes)

    if (args.modelfilename != ''):
        serialize(model,args.modelfilename)
        
    #aggregated predictions by geometric mean
    y_pred = []
    #multiple single predictions of the classifiers
    y_multi_pred = []

    print 'Performance on dev set:'

    #now test on heldout ids (dev set)
    for myid in dev_ids:
        print 'testing',myid
        pred,multi_pred = model.predict_utterance(myid)
        y_multi_pred.append(multi_pred)
        y_pred.append(pred)

    print lang2num
    print 'Single classifier performance scores:'
    for i in xrange(len(multi_pred)):
        print 'Pred #',i,':'
        #print 'Window size', window_sizes[i],'step size',step_sizes[i]
        print_classificationreport(dev_classes, [pred[i] for pred in y_multi_pred])
    print '+'*50
    print lang2num
    print 'Fused scores:'
    print_classificationreport(dev_classes, y_pred)
