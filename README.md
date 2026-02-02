Repository for viewing local database information within TTU APD Lab. 

**Database query tool**

The only requirement for using the database query tool `all_in_one.sh` is installation of the PostgresQL software, as described here: https://www.postgresql.org/download/

Once this is set up, can run the program with:

```
./all_in_one.sh
```

Tutorial for usage is linked here: https://eventreg.ads.ttu.edu/event/237/contributions/610/attachments/303/625/Database%20query%20tutorial-2.pdf

**Summary plotting tools**

More dependencies are needed to make sure this runs. These are listed in `dependencies.txt`. A virtual environment is recommended for making this work.

```
python3 -m venv venv                      
source venv/bin/activate
python3 -m pip install -r dependencies.txt
```

Once dependencies are installed, then can run with:
```
python3 summary_plotter_interactive.py
```
Tutorial to be uploaded soon.
------------------------------------
More updates and tools TBA
