#!/usr/bin/env python
# -*- coding: UTF-8 -*-

# Copyright 2016 Timothy Dozat
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import tensorflow as tf
from collections import Counter

from lib.etc.k_means import KMeans
from configurable import Configurable
from vocab import Vocab
from metabucket import Metabucket

#***************************************************************
class Dataset(Configurable):
  """"""
  
  #=============================================================
  def __init__(self, filename, vocabs, builder, *args, **kwargs):
    """"""
    
    super(Dataset, self).__init__(*args, **kwargs)
    self.vocabs = vocabs

    self.trigger_indices = [i for s, i in self.vocabs[3].iteritems() if self.trigger_str in s]

    self._file_iterator = self.file_iterator(filename)
    self._train = (filename == self.train_file)
    self._metabucket = Metabucket(self._config, n_bkts=self.n_bkts)
    self._data = None
    self.rebucket()


    self.inputs = tf.placeholder(dtype=tf.int32, shape=(None,None,None), name='inputs')
    self.targets = tf.placeholder(dtype=tf.int32, shape=(None,None,None), name='targets')
    self.builder = builder()
  
  #=============================================================
  def file_iterator(self, filename):
    """"""
    
    with open(filename) as f:
      if self.lines_per_buffer > 0:
        buff = [[]]
        while True:
          line = f.readline()
          while line:
            line = line.strip().split()
            if line:
              buff[-1].append(line)
            else:
              if len(buff) < self.lines_per_buffer:
                if len(buff[-1]) > 0:
                  buff.append([])
                else:
                  buff[-1] = []
              else:
                break
            line = f.readline()
          if not line:
            f.seek(0)
          else:
            buff = self._process_buff(buff)
            yield buff
            line = line.strip().split()
            if line:
              buff = [[line]]
            else:
              buff = [[]]
      else:
        buff = [[]]
        for line in f:
          line = line.strip().split()
          if line:
            buff[-1].append(line)
          else:
            if len(buff[-1]) > 0:
              buff.append([])
            else:
              buff[-1] = []
        if buff[-1] == []:
          buff.pop()
        buff = self._process_buff(buff)
        while True:
          yield buff
  
  #=============================================================
  def _process_buff(self, buff):
    """"""
    
    words, tags, rels, srls, trigs = self.vocabs
    sents = 0
    toks = 0
    examples = 0
    buff2 = []
    for i, sent in enumerate(buff):
      # if not self.conll2012 or (self.conll2012 and len(list(sent)) > 1):
      # print(sent, len(sent))
      sents += 1
      trigger_indices = []
      for j, token in enumerate(sent):
        toks += 1
        if self.conll:
          word, tag1, tag2, head, rel = token[words.conll_idx], token[tags.conll_idx[0]], token[tags.conll_idx[1]], token[6], token[rels.conll_idx]
          if rel == 'root':
            head = j
          else:
            head = int(head) - 1
          buff[i][j] = (word,) + words[word] + tags[tag1] + tags[tag2] + (head,) + rels[rel]
        elif self.conll2012:
          word, tag1, tag2, head, rel = token[words.conll_idx], token[tags.conll_idx[0]], token[tags.conll_idx[1]], token[6], token[rels.conll_idx]
          # print(word, tag1, tag2, head, rel)
          if rel == 'root':
            head = j
          else:
            head = int(head) - 1
          # for s in srls.conll_idx:
          srl_fields = [token[idx] if idx < len(token)-1 else 'O' for idx in srls.conll_idx]
          # if "B-ARGM-MOD/B-ARG1" in srl_fields:
          #   print("stuff:",  word, tag1, tag2, head, rel)
          #   print("srl_fields", [token[idx] for idx in range(len(token)-1)])
          srl_tags = [srls[s][0] for s in srl_fields]
          is_trigger = np.any([s in self.trigger_indices for s in srl_tags])
          if is_trigger:
            trigger_indices.append(j)
          buff[i][j] = (word,) + words[word] + tags[tag1] + trigs[str(is_trigger)] + tags[tag2] + (head,) + rels[rel] + tuple(srl_tags)
      if self.one_example_per_predicate:
        # grab the sent
        # should be sent_len x sent_elements
        sent = np.array(buff[i])
        is_trigger_idx = 4
        srl_start_idx = 8
        srl_part = sent[:, srl_start_idx:]
        rest_part = sent[:, :srl_start_idx]
        # print("sent:", sent)
        if trigger_indices:
          for j, t_idx in enumerate(trigger_indices):
            # should be sent_len x sent_elements
            rest_part[:, is_trigger_idx] = trigs["False"][0]
            rest_part[t_idx, is_trigger_idx] = trigs["True"][0]
            correct_srls = srl_part[:, j]
            new_sent = np.concatenate([rest_part, np.expand_dims(correct_srls, -1)], axis=1)
            buff2.append(new_sent)
            # print("new sent", new_sent)
            examples += 1
      else:
        buff2.append(sent)
        examples += 1
        # want to add a copy for each trigger
        # sent.insert(0, ('root', Vocab.ROOT, Vocab.ROOT, Vocab.ROOT, Vocab.ROOT, 0, Vocab.ROOT))
    print("Loaded %d sentences with %d tokens, %d examples (%s)" % (sents, toks, examples, self.name))
    return buff2
  
  #=============================================================
  def reset(self, sizes):
    """"""
    
    self._data = []
    self._targets = []
    self._metabucket.reset(sizes)
    return
  
  #=============================================================
  def rebucket(self):
    """"""

    buff = self._file_iterator.next()
    len_cntr = Counter()
    
    for sent in buff:
      len_cntr[len(sent)] += 1
    self.reset(KMeans(self.n_bkts, len_cntr).splits)
    
    for sent in buff:
      self._metabucket.add(sent)
    self._finalize()
    return
  
  #=============================================================
  def _finalize(self):
    """"""
    
    self._metabucket._finalize()
    return
  
  #=============================================================
  def get_minibatches(self, batch_size, input_idxs, target_idxs, shuffle=True):
    """"""
    
    minibatches = []
    for bkt_idx, bucket in enumerate(self._metabucket):
      if batch_size == 0:
        n_splits = 1
      else:
        n_tokens = len(bucket) * bucket.size
        n_splits = max(n_tokens // batch_size, 1)
      if shuffle:
        range_func = np.random.permutation
      else:
        range_func = np.arange
      arr_sp = np.array_split(range_func(len(bucket)), n_splits)
      for bkt_mb in arr_sp:
        minibatches.append( (bkt_idx, bkt_mb) )
    if shuffle:
      np.random.shuffle(minibatches)
    for bkt_idx, bkt_mb in minibatches:
      feed_dict = {}
      data = self[bkt_idx].data[bkt_mb]
      sents = self[bkt_idx].sents[bkt_mb]
      maxlen = np.max(np.sum(np.greater(data[:,:,0], 0), axis=1))
      np.set_printoptions(threshold=np.nan)

      # print("inputs:", data[:,:maxlen,input_idxs])
      # print("targets:", data[:,:maxlen,min(target_idxs):maxlen+max(target_idxs)])


      feed_dict.update({
        # 0, 1, 2, 3: word, word, tag1, trig
        self.inputs: data[:,:maxlen,input_idxs],
        # 4, 5, 6, ...: tag2, arc, rel, srls
        self.targets: data[:,:maxlen,min(target_idxs):maxlen+max(target_idxs)]
      })
      yield feed_dict, sents
  
  #=============================================================
  @property
  def n_bkts(self):
    if self._train:
      return super(Dataset, self).n_bkts
    else:
      return super(Dataset, self).n_valid_bkts
  
  #=============================================================
  def __getitem__(self, key):
    return self._metabucket[key]
  def __len__(self):
    return len(self._metabucket)
