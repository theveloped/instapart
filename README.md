## Development environment
)
Install anaconda (64 bit Python 3.7 version)) on your machine from the following link:

https://www.anaconda.com/distribution/

After installing make sure you start a new python 2.7 envoronment and activate it:

```
conda create -n python27 python=2.7
conda activate python27
```

After this install PythonOcc using conda:

```
conda install -c tpaviot -c conda-forge -c dlr-sc -c pythonocc -c oce -c 3dhubs pythonocc-core==0.18.1 python=2.7
```

Finally install the requirements using the requirement.txt file

```
pip install -r requirements.txt
```

You should now be all ready to got to run the tool like so:

```
python instapart.py -h
```




## Build

```
python setup.py build_ext --inplace

pyinstaller instapart.spec -y
```

## Test
```
.\dist\instapart\instapart.exe .\examples\xml\batch_input_file.xml

.\dist\instapart\instapart.exe auto .\examples\assy\IEA-000204.stp -r -o ./temp
```

## Setup
Build setup using `Inno setup` and the provided script: `setup_script.iss`


## Decompile
```
python dist\pyinstxtractor.py .\dist\instapart\instapart.exe
```