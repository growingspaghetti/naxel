# repo-manipulator

repo-manipulator manipulates data in a NAS repository using commands.

You can exit app using `exit` command.

# commands
```
ls systems # list system names in /systems/ decoding base32
add systems sys3 # create a file with the system name in /systems/ encoding base32
cat systems sys4 # print contents finding the maching file by name
get systems sys3 # get the contents finding the maching file by name, save it in downloads, then open it with the editor written below (mousepad).
clear systems sys3 # like `get` command this opens the editor but with the empty system document.
push systems sys3 # reads the contents after finding the file in downloads, then write it in the file in the repository.

ls schedules # list schedule names in /systems/ decoding base32
add schedules sc1 # create a file with the system name in /schedules/ encoding base32
cat schedules sc4 # print contents finding the maching file by name
get schedules sc3 # get the contents finding the maching file by name, save it in downloads, then open it with the editor written below (mousepad).
clear schedule sys3 # like `get` command this opens the editor but with the empty schedule document.
push schedules sc3 # reads the contents after finding the file in downloads, then write it in the file in the repository

export systems foo.csv # export data in systems to the csv and open with the editor.
export schedules bar.csv # export data in systems to the csv and open with the editor.

exit # terminates this application
```

# developing language
python

# NAS repository structure
/systems/
base32-named-sys1.txt
base32-named-sys2.txt
...

/schedules/
base32-named-schedule-name1.txt
base32-named-schedule-name2.txt
...

# how to specify repository path
repository.root in settings.ini (use `dummy-repo` while developing)



# editor to launch
mouthpad

# document formats

## system
repetition of this section.
```
👉👉👉👉👉👉👉👉👉👉👈👈👈👈👈👈👈👈👈👈
👉machine👈
m1
👉schedule👈
sche1
👉time👈
12:03
👉notes👈
some
memo
here
👉props1👈

👉props2👈

👉props3👈

```

```
👉👉👉👉👉👉👉👉👉👉👈👈👈👈👈👈👈👈👈👈
👉machine👈
m1
👉schedule👈
sche1
👉time👈
02:23
👉notes👈
some
memo
here
👉props1👈

👉props2👈

👉props3👈

👉👉👉👉👉👉👉👉👉👉👈👈👈👈👈👈👈👈👈👈
👉machine👈
m2
👉schedule👈
sche8
👉time👈
12:22
👉notes👈
optional
👉props1👈

👉props2👈

👉props3👈

```

### empty system document
```
👉👉👉👉👉👉👉👉👉👉👈👈👈👈👈👈👈👈👈👈
👉machine👈

👉schedule👈

👉time👈

👉notes👈

👉props1👈

👉props2👈

👉props3👈

```

## schedule
one line or one line + \n. repetition of yyyy/mm/dd with commas.
```
1234/12/31,2000/06/01
```

```
1234/12/31,2000/06/01

```

### empty schedule document
```

```

# export to csv
saved to `downloads`.
## systems
```csv
system_name, machine_name, schedule_name, notes
sys1, m1, sche3, foobarbaz
sys1, m2, sche7, 
sys2, m4, sche7, hoge
```
## schedules
```csv
schedule_name, dates
sche1, 1234/11/12 1234/11/12 1234/12/12 1234/11/13
sche5, 1234/11/12 1234/12/12 1234/11/13
```
