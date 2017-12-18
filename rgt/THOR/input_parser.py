#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
THOR detects differential peaks in multiple ChIP-seq profiles associated
with two distinct biological conditions.

Copyright (C) 2014-2016 Manuel Allhoff (allhoff@aices.rwth-aachen.de)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

@author: Manuel Allhoff

# this file we need to merge with something else;;
Anyway a whole structure you need to draw... On my computer
"""

from __future__ import print_function
import os
import sys
import re
import shutil
from os.path import basename, join, isdir, exists, isfile
from optparse import OptionParser, OptionGroup
from datetime import datetime
import numpy as np

from rgt.Util import which, npath
from rgt import __version__
import configuration


def get_data_block(filepath, feature):
    with open(filepath) as f:
        data = []
        read = False
        for line in f:
            line = line.strip()
            if line == '':
                continue
            if line.startswith("#") and line == "#" + str(feature):
                read = True
            
            if line.startswith("#") and line != "#" + str(feature):
                read = False
            
            if not line.startswith("#") and read:
                data.append(line)
                
    if len(data) == 1 and not (feature == "rep1" or feature == "rep2" or feature == "inputs1" or feature == "inputs2"):
        return data[0]
    else:
        return data


def input_parser(filepath):
    bamfiles_1 = get_data_block(filepath, "rep1")
    bamfiles_1 = map(npath, bamfiles_1)

    for bamfile in bamfiles_1:
        if not isfile(bamfile):
            print("BAM file %s does not exist!" % bamfile, file=sys.stderr)
            sys.exit()

    bamfiles_2 = get_data_block(filepath, "rep2")
    bamfiles_2 = map(npath, bamfiles_2)

    for bamfile in bamfiles_2:
        if not isfile(bamfile):
            print("BAM file %s does not exist!" % bamfile, file=sys.stderr)
            sys.exit()

    # genome is optional, so if we get an empty list
    # we set it to None, otherwise we normalise the path
    genome = get_data_block(filepath, "genome")
    if genome:
        genome = npath(genome)
        if not isfile(genome):
            print("Genome file %s does not exist!" % genome, file=sys.stderr)
            sys.exit()
    else:
         genome = None

    chrom_sizes_file = npath(get_data_block(filepath, "chrom_sizes"))
    if chrom_sizes_file:
        chrom_sizes_file = npath(chrom_sizes_file)
        if not isfile(chrom_sizes_file):
            print("chrom size file %s does not exist!" % chrom_sizes_file, file=sys.stderr)
            sys.exit()
    else:
        chrom_sizes_file = None

    inputs_1 = get_data_block(filepath, "inputs1")
    inputs_1 = map(npath, inputs_1)

    for bamfile in inputs_1:
        if not isfile(bamfile):
            print("BAM file %s does not exist!" % bamfile, file=sys.stderr)
            sys.exit()

    inputs_2 = get_data_block(filepath, "inputs2")
    inputs_2 = map(npath, inputs_2)
    for bamfile in inputs_1:
        if not isfile(bamfile):
            print("BAM file %s does not exist!" % bamfile, file=sys.stderr)
            sys.exit()


    dims = [2, len(bamfiles_1)]
    
    if not inputs_1 and not inputs_2:
        inputs = None
    else:
        inputs = [inputs_1, inputs_2]

    return [bamfiles_1, bamfiles_2], genome, chrom_sizes_file, inputs, dims

class HelpfulOptionParser(OptionParser):
    """An OptionParser that prints full help on errors."""
    def error(self, msg):
        self.print_help(sys.stderr)
        self.exit(2, "\n%s: error: %s\n" % (self.get_prog_name(), msg))

    def confirm(self, prompt=None, resp=False):
        """prompts for yes or no response from the user. Returns True for yes and
        False for no.

        'resp' should be set to the default value assumed by the caller when
        user simply types ENTER.

        >>> confirm(prompt='Create Directory?', resp=True)
        Create Directory? [y]|n:
        True
        >>> confirm(prompt='Create Directory?', resp=False)
        Create Directory? [n]|y:
        False
        >>> confirm(prompt='Create Directory?', resp=False)
        Create Directory? [n]|y: y
        True

        """
        if prompt is None:
            prompt = 'Confirm'

        if resp:
            prompt = '%s [%s]|%s: ' % (prompt, 'y', 'n')
        else:
            prompt = '%s [%s]|%s: ' % (prompt, 'n', 'y')

        while True:
            ans = raw_input(prompt)
            if not ans:
                return resp
            if ans not in ['y', 'Y', 'n', 'N']:
                print('please enter y or n.')
                continue
            if ans == 'y' or ans == 'Y':
                return True
            if ans == 'n' or ans == 'N':
                return False

    def callback_list(self, option, opt, value, parser):
        setattr(parser.values, option.dest, map(lambda x: int(x), value.split(',')))

    def callback_list_float(self, option, opt, value, parser):
        setattr(parser.values,option.dest, map(lambda x: float(x), value.split(',')))

    def transform_list_with_dim(self,list_data, dim):
        """for example like: list for len and then we transform it into list with one certain dimension"""
        tmp = np.asarray(list_data)
        tmp=tmp.reshape(dim)
        return map(list,tmp)

    def is_valid_dim(self, list_data, dims):
        """test if data given satisfies the dimension required"""
        if len(list_data) == dims[0] * dims[1]:
            return True
        else:
            return False


def handle_input():
    parser = HelpfulOptionParser(usage=__doc__)

    parser.add_option("-n", "--name", default=None, dest="name", type="string",
                      help="Experiment's name and prefix for all files that are created.")
    parser.add_option("-m", "--merge", default=False, dest="merge", action="store_true",
                      help="Merge peaks which have a distance less than the estimated mean fragment size "
                           "(recommended for histone data). [default: do not merge]")
    parser.add_option("--no-merge-bin", default=True, dest="merge_bin", action="store_false",
                      help="Merge the overlapping bin before filtering by p-value."
                           "[default: Merging bins]")
    parser.add_option("--housekeeping-genes", default=None, dest="housekeeping_genes", type="str",
                      help="Define housekeeping genes (BED format) used for normalizing. [default: %default]")
    parser.add_option("--output-dir", dest="outputdir", default=None, type="string",
                      help="Store files in output directory. [default: %default]")
    parser.add_option("--report", dest="report", default=False, action="store_true",
                      help="Generate HTML report about experiment. [default: %default]")
    parser.add_option("--deadzones", dest="deadzones", default=None,
                      help="Define blacklisted genomic regions avoided for analysis (BED format). [default: %default]")
    parser.add_option("--no-correction", default=False, dest="no_correction", action="store_true",
                      help="Do not use multipe test correction for p-values (Benjamini/Hochberg). [default: %default]")
    parser.add_option("-p", "--pvalue", dest="pcutoff", default=0.1, type="float",
                      help="P-value cutoff for peak detection. Call only peaks with p-value lower than cutoff. "
                           "[default: %default]")
    parser.add_option("--exts", default=[], dest="exts", type="str", action='callback', callback=parser.callback_list,
                      help="Read's extension size for Signal files (comma separated list for each BAM file in config "
                           "file). If option is not chosen, estimate extension sizes. [default: %default]")
    parser.add_option("--exts-inputs", default=[], dest="exts_inputs", type="str", action='callback', callback=parser.callback_list,
                      help="Read's extension size for Input files (comma separated list for each BAM file in config "
                           "file). If option is not chosen, estimate extension sizes. [default: %default]")
    parser.add_option("--factors-inputs", default=[], dest="factors_inputs", type="str", action="callback",
                      callback=parser.callback_list_float,
                      help="Normalization factors for input-DNA (comma separated list for each BAM file in config "
                           "file). If option is not chosen, estimate factors. [default: %default]")
    parser.add_option("--scaling-factors", default=[], dest="scaling_factors_ip", type="str", action='callback',
                      callback=parser.callback_list_float,
                      help="Scaling factor for each BAM file (not control input-DNA) as comma separated list for "
                           "each BAM file in config file. If option is not chosen, follow normalization strategy "
                           "(TMM or HK approach) [default: %default]")
    parser.add_option("--call-peaks", dest="call_peaks", default=True, action="store_true",
                      help="DO call peaks, if setting False, only output normalized bigWig files. [default: %default]")
    parser.add_option("--save-input", dest="save_input", default=False, action="store_true",
                      help="Save input-DNA file if available. [default: %default]")
    parser.add_option("--version", dest="version", default=False, action="store_true",
                      help="Show script's version.")

    group = OptionGroup(parser, "Advanced options")
    group.add_option("--regions", dest="regions", default=None, type="string",
                     help="Define regions (BED format) to restrict the analysis, that is, where to train the HMM and "
                          "search for DPs. It is faster, but less precise.")
    group.add_option("-b", "--binsize", dest="binsize", default=100, type="int",
                     help="Size of underlying bins for creating the signal. [default: %default]")
    group.add_option("-s", "--step", dest="stepsize", default=50, type="int",
                     help="Stepsize with which the window consecutively slides across the genome to create the "
                          "signal. [default: %default]")
    group.add_option("--debug", default=False, dest="debug", action="store_true",
                     help="Output debug information. Warning: space consuming! [default: %default]")
    group.add_option("--no-gc-content", dest="no_gc_content", default=False, action="store_true",
                     help="Do not normalize towards GC content. [default: %default]")
    group.add_option("--norm-regions", default=None, dest="norm_regions", type="str",
                     help="Restrict normalization to particular regions (BED format). [default: %default]")
    group.add_option("-f", "--foldchange", dest="foldchange", default=1.6, type="float",
                     help="Fold change parameter to define training set (t_1, see paper). [default: %default]")
    group.add_option("-t", "--threshold", dest="threshold", default=95, type="float",
                     help="Minimum signal support for differential peaks to define training set as percentage "
                          "(t_2, see paper). [default: %default]")
    group.add_option("--size", dest="size_ts", default=1000, type="int",
                     help="Number of bins the HMM's training set constists of. [default: %default]")
    group.add_option("--par", dest="par", default=1, type="int",
                     help="Percentile for p-value postprocessing filter. [default: %default]")
    group.add_option("--poisson", default=False, dest="poisson", action="store_true",
                     help="Use binomial distribution as emmission. [default: %default]")
    group.add_option("--single-strand", default=False, dest="singlestrand", action="store_true",
                     help="Allow single strand BAM file as input. [default: %default]")
    group.add_option("--m_threshold", default=80, dest="m_threshold", type="int",
                     help="Define the M threshold of percentile for training TMM. [default: %default]")
    group.add_option("--a_threshold", default=95, dest="a_threshold", type="int",
                     help="Define the A threshold of percentile for training TMM. [default: %default]")
    group.add_option("--rmdup", default=False, dest="rmdup", action="store_true",
                     help="Remove the duplicate reads [default: %default]")
    parser.add_option_group(group)

    (options, args) = parser.parse_args()
    options.save_wig = True
    # options.exts_inputs = None # we set it as an option
    options.verbose = True
    options.hmm_free_para = False

    if options.version:
        print("")
        print(__version__)
        sys.exit()

    if len(args) != 1:
        parser.error("Please give config file")

    config_path = npath(args[0])

    if not isfile(config_path):
        parser.error("Config file %s does not exist!" % config_path)

    bamfiles, genome, chrom_sizes, inputs, dims = input_parser(config_path)

    if not genome:
        options.no_gc_content = True

    if options.exts and not parser.is_valid_dim(options.exts, dims):
        parser.error("Number of Extension Sizes must equal number of bamfiles")
    if options.exts:
        options.exts = parser.transform_list_with_dim(options.exts, dim=dims)

    if options.exts_inputs and not parser.is_valid_dim(options.exts_inputs, dims):
        parser.error("Number of Input Extension Sizes must equal number of input bamfiles")
    if options.exts_inputs:
        options.exts_inputs = parser.transform_list_with_dim(options.exts_inputs, dim=dims)

    if options.scaling_factors_ip and not parser.is_valid_dim(options.scaling_factors_ip, dims):
        parser.error("Number of scaling factors for IP must equal number of bamfiles")
    if options.scaling_factors_ip:
        options.scaling_factors_ip = parser.transform_list_with_dim(options.scaling_factors_ip, dim=dims)

    if not inputs and options.factors_inputs:
        print("As no input-DNA, do not use input-DNA factors", file=sys.stderr)
        options.factors_inputs = None

    if options.factors_inputs and not parser.is_valid_dim(options.factors_inputs, dims):
        parser.error("factors for input-DNA must equal number of BAM files!")
    if options.factors_inputs:
        options.factors_inputs = parser.transform_list_with_dim(options.factors_inputs, dim=dims)

    if options.regions:
        if not isfile(options.regions):
            parser.error("Region file %s does not exist!" % options.regions)

    if options.name is None:
        d = str(datetime.now()).replace("-", "_").replace(":", "_").replace(" ", "_").replace(".", "_").split("_")
        options.name = "THOR-exp" + "-" + "_".join(d[:len(d) - 1])

    if not which("wigToBigWig") or not which("bedGraphToBigWig") or not which("bigWigMerge"):
        print("Warning: wigToBigWig, bigWigMerge or bedGraphToBigWig not found! Signal will not be stored!",
              file=sys.stderr)

    if options.outputdir:
        options.outputdir = npath(options.outputdir)
        # if exist then we judge if there exists one file with peak amd if it's then we save it;
        # else, we will delete the files
        if isdir(options.outputdir):
            if np.any(map(lambda x: re.search(r".*diffpeaks.bed$", x),os.listdir(options.outputdir))):
                if parser.confirm(prompt="delete existing results?", resp=True):
                    shutil.rmtree(options.outputdir)
                else:
                    parser.error("Output directory exists and contains files with names starting with your chosen experiment name! "
                                 "Do nothing to prevent file overwriting!")
            else:
                shutil.rmtree(options.outputdir)

        if not exists(options.outputdir):
            os.mkdir(options.outputdir)
    else:
        options.outputdir = os.getcwd()

    options.name = join(options.outputdir, options.name)

    if options.report and isdir(join(options.outputdir, 'report_'+basename(options.name))):
        parser.error("Folder 'report_"+basename(options.name)+"' already exits in output directory!" 
                     "Do nothing to prevent file overwriting! "
                     "Please rename report folder or change working directory of THOR with the option --output-dir")

    if options.report:
        os.mkdir(join(options.outputdir, 'report_'+basename(options.name)+"/"))
        os.mkdir(join(options.outputdir, 'report_'+basename(options.name), 'pics/'))
        os.mkdir(join(options.outputdir, 'report_'+basename(options.name), 'pics/data/'))

        configuration.FOLDER_REPORT = join(options.outputdir, 'report_'+basename(options.name)+"/")
        configuration.FOLDER_REPORT_PICS = join(options.outputdir, 'report_'+basename(options.name), 'pics/')
        configuration.FOLDER_REPORT_DATA = join(options.outputdir, 'report_'+basename(options.name), 'pics/data/')
        configuration.OUTPUTDIR = options.outputdir
        configuration.NAME = options.name

    if not inputs:
        print("Warning: Do not compute GC-content, as there is no input file", file=sys.stderr)

    if not genome:
        print("Warning: Do not compute GC-content, as there is no genome file", file=sys.stderr)

    options.call_peaks = True

    return options, bamfiles, genome, chrom_sizes, dims, inputs
