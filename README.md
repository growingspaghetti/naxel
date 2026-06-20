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
len systems sys3 # prints "%d" that is the length of the non-empty records contained in this system document.
diff systems sys3 # compares the objects in the latest version in the repository with those of the previous one and shows difference in json having "deleted" and "added".
push systems sys3 # reads the contents after finding the file in downloads, then write it in the file in the repository.

ls schedules # list schedule names in /schedules/ decoding base32
add schedules sc1 # create a file with the schedule name in /schedules/ encoding base32
cat schedules sc4 # print contents finding the maching file by name
get schedules sc3 # get the contents finding the maching file by name, save it in downloads, then open it with the editor written below (mousepad).
clear schedules sc3 # like `get` command this opens the editor but with the empty schedule document.
len schedules sc3 # prints "%d" that is how many dates contained in this schedule document.
diff schedules sys3 # compares the dates in the latest version in the repository with those of the previous one and shows difference in json having "deleted" and "added".
push schedules sc3 # reads the contents after finding the file in downloads, then write it in the file in the repository

ls contacts # list contact names in /contacts/ decoding base32
add contacts cont1 # create a file with the contact name in /contacts/ encoding base32
cat contacts cont4 # print contents finding the maching file by name
get contacts cont3 # get the contents finding the maching file by name, save it in downloads, then open it with the editor written below (mousepad).
clear contacts c3 # like `get` command this opens the editor but with the empty contact document.
len contacts c3 # prints "%d" that is how many contacts contained in this contact document.
diff contacts c3 # compares the phone numbers in the latest version in the repository with those of the previous one and shows difference in json having "deleted" and "added".
push contact c3 # reads the contents after finding the file in downloads, then write it in the file in the repository

export systems foo.csv # export data in systems to the csv and open with the editor.
export schedules bar.csv # export data in schedules to the csv and open with the editor.
export contacts baz.csv # export data in contacts to the csv and open with the editor.

export systems foo.csv --jtable # export data in systems to the csv and open it with jtable gui.
export schedules bar.csv --jtable # export data in schedules to the csv and open it with jtable gui.
export contacts baz.csv --jtable # export data in contacts to the csv and open it with jtable gui.

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

/contacts/
base32-named-contact-name1.txt
base32-named-contact-name2.txt
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
👉id👈
#id1
👉schedule👈
sche1
👉time👈
12:03
👉notes👈
some
memo
here
👉contact👈
con4
👉props1👈

👉props2👈

👉props3👈

```

```
👉👉👉👉👉👉👉👉👉👉👈👈👈👈👈👈👈👈👈👈
👉machine👈
m1
👉id👈
#id12
👉schedule👈
sche1
👉time👈
02:23
👉notes👈
some
memo
here
👉contact👈
c3
👉props1👈

👉props2👈

👉props3👈

👉👉👉👉👉👉👉👉👉👉👈👈👈👈👈👈👈👈👈👈
👉machine👈
m2
👉id👈
#1222
👉schedule👈
sche8
👉time👈
12:22
👉notes👈
optional
👉contact👈
con5
👉props1👈

👉props2👈

👉props3👈

```

### empty system document
```
👉👉👉👉👉👉👉👉👉👉👈👈👈👈👈👈👈👈👈👈
👉machine👈

👉id👈

👉schedule👈

👉time👈

👉notes👈

👉contact👈

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

## contact
one line or one line + \n. repetition of ([0-9] or [-] or [+])+ with commas.
```
03-1234-5678,09012345678,+81-0100-0331
```

```
03-1234-5678,09012345678,+81-0100-0331

```

### empty contact document
```

```

# export to csv
saved to `downloads`.
## systems
```csv
system_name, id, machine_name, schedule_name, notes
sys1, #id2, m1, sche3, foobarbaz
sys1, #1, m2, sche7, 
sys2, #id2, m4, sche7, hoge
```
## schedules
```csv
schedule_name, dates
sche1, 1234/11/12 1234/11/12 1234/12/12 1234/11/13
sche5, 1234/11/12 1234/12/12 1234/11/13
```
## contacts
```csv
contact_name, numbers
con1, 03-1234-5678 09012345678 +81-0100-0331
c3, 03-9999-9999
```
