#!/usr/bin/env python
import copy
from ase import Atoms
import numpy as np
import os
import pickle
from phonopy import Phonopy
from phonopy.structure.atoms import PhonopyAtoms
from phonopy.units import VaspToTHz
from phonopy.file_IO import (write_FORCE_CONSTANTS, write_disp_yaml,
                             parse_FORCE_SETS)
from phonopy.interface.vasp import write_supercells_with_displacements
import copy
#from concurrent.futures import ProcessPoolExecutor
#from multiprocessing import Pool
from pathos.multiprocessing import ProcessingPool as Pool


def calculate_phonon(atoms,
                     calc=None,
                     forces_set_file=None,
                     ndim=np.eye(3),
                     primitive_matrix=np.eye(3),
                     distance=0.01,
                     factor=VaspToTHz,
                     is_symmetry=True,
                     symprec=1e-5,
                     func=None,
                     prepare_initial_wavecar=False,
                     skip=None,
                     parallel=True,
                     **func_args):
    """
    """
    if 'magmoms' in atoms.arrays:
        is_mag = True
    else:
        is_mag = False
    # 1. get displacements and supercells
    if calc is not None:
        atoms.set_calculator(calc)
    # bulk = PhonopyAtoms(atoms=atoms)
    if is_mag:
        bulk = PhonopyAtoms(
            symbols=atoms.get_chemical_symbols(),
            scaled_positions=atoms.get_scaled_positions(),
            cell=atoms.get_cell(),
            magmoms=atoms.arrays['magmoms'], )
    else:
        bulk = PhonopyAtoms(
            symbols=atoms.get_chemical_symbols(),
            scaled_positions=atoms.get_scaled_positions(),
            cell=atoms.get_cell())

    phonon = Phonopy(
        bulk,
        ndim,
        primitive_matrix=primitive_matrix,
        factor=factor,
        symprec=symprec)
    phonon.generate_displacements(distance=distance)
    disps = phonon.get_displacements()
    for d in disps:
        print(("[phonopy] %d %s" % (d[0], d[1:])))
    supercell0 = phonon.get_supercell()
    supercells = phonon.get_supercells_with_displacements()
    write_supercells_with_displacements(supercell0, supercells)
    write_disp_yaml(disps, supercell0)

    # 2. calculated forces.
    if forces_set_file is not None:
        symmetry = phonon.get_symmetry()
        set_of_forces = parse_FORCE_SETS(is_translational_invariance=False,filename=forces_set_file)#['first_atoms']
        #set_of_forces=np.array(set_of_forces)
        #set_of_forces=[np.asarray(f) for f in set_of_forces]
        phonon.set_displacement_dataset(set_of_forces)
        phonon.produce_force_constants()
    else:
        set_of_forces = []

        if prepare_initial_wavecar and skip is None:
            scell = supercell0
            cell = Atoms(
                symbols=scell.get_chemical_symbols(),
                scaled_positions=scell.get_scaled_positions(),
                cell=scell.get_cell(),
                pbc=True)
            if is_mag:
                cell.set_initial_magnetic_moments(
                    atoms.get_initial_magnetic_moments())
            mcalc = copy.deepcopy(calc)
            mcalc.set(lwave=True, lcharg=True)
            cell.set_calculator(mcalc)
            dir_name = "SUPERCELL0"
            cur_dir = os.getcwd()
            if not os.path.exists(dir_name):
                os.mkdir(dir_name)
            os.chdir(dir_name)
            mcalc.scf_calculation()
            os.chdir(cur_dir)

        def calc_force(iscell):
            scell=supercells[iscell]
            cell = Atoms(
                symbols=scell.get_chemical_symbols(),
                scaled_positions=scell.get_scaled_positions(),
                cell=scell.get_cell(),
                pbc=True)
            if is_mag:
                cell.set_initial_magnetic_moments(
                    atoms.get_initial_magnetic_moments())
            cell.set_calculator(copy.deepcopy(calc))
            dir_name = "PHON_CELL%s" % iscell
            cur_dir = os.getcwd()
            if not os.path.exists(dir_name):
                os.mkdir(dir_name)
            if prepare_initial_wavecar:
                os.system('ln -s %s %s' %
                          (os.path.abspath("SUPERCELL0/WAVECAR"),
                           os.path.join(dir_name, 'WAVECAR')))

            os.chdir(dir_name)
            forces = cell.get_forces()
            print("[Phonopy] Forces: %s" % forces)
            # Do something other than calculating the forces with func.
            # func: func(atoms, calc, func_args)
            if func is not None:
                func(cell, calc, **func_args)
            os.chdir(cur_dir)
            drift_force = forces.sum(axis=0)
            print("[Phonopy] Drift force:", "%11.5f" * 3 % tuple(drift_force))
            # Simple translational invariance
            for force in forces:
                force -= drift_force / forces.shape[0]
            return forces

        #with ProcessPoolExecutor() as executor:
        #    if skip is not None:
        #        skip=0
        #    set_of_forces=executor.map(calc_force,list(range(skip,len(supercells))))
        if skip is None:
            iskip=0
        else:
            iskip=skip
        if parallel:
            p=Pool()
            set_of_forces=p.map(calc_force,list(range(iskip,len(supercells))))
        else:
            set_of_forces=[]
            for iscell, scell in enumerate(supercells[iskip:]):
                set_of_forces.append(calc_force(iscell))

        #phonon.set_displacement_dataset(set_of_forces)
        phonon.produce_force_constants(forces=np.array(set_of_forces))
    # Phonopy post-process
    print('==============')
    print(phonon._displacement_dataset['first_atoms'])
    #phonon.produce_force_constants(forces=np.array(set_of_forces))
    #phonon.produce_force_constants()
    force_constants = phonon.get_force_constants()
    #print(force_constants)
    write_FORCE_CONSTANTS(force_constants, filename='FORCE_CONSTANTS')
    #print("[Phonopy] Phonon frequencies at Gamma:")
    #for i, freq in enumerate(phonon.get_frequencies((0, 0, 0))):
    #    print(("[Phonopy] %3d: %10.5f THz" % (i + 1, freq)))  # THz
    #    print(("[Phonopy] %3d: %10.5f cm-1" % (i + 1, freq * 33.35)))  #cm-1
    with open('phonon.pickle', 'wb') as myfile:
        pickle.dump(phonon, myfile)
    return phonon
