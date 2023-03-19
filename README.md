# pyMMDVM
## a python interface (over serial) to an MMDVM modem or hotspot

Why would you want this?

Well, for one, it's effectively a high level documentation of the MMDVM
serial protocol. I'll include the docs and links to other code that
I referenced to write it, too.

For two, it allows some very high level work with these modems. Low-speed
serial  is simply not demanding on a CPU, and the tradeoff to a high
level language like Python is strongly in your favor if you're learning
or building a proof of concept. You can do more, faster, and with a
lot less effort, so Python makes a fantastic language for research and
development while still being very useful in production.

For three - I like Python. 
We don't all like the same things, and we needn't.

If you don't like it, feel free to port this code and all its capabilities
to some other language. Let me know how far you get, lol.

For four, I need to interface with a serial MMDVM modem in C on a
different platform and wanted to be sure I fully understood how to
communicate with it on a platform where the hardware wouldn't be in the
way. Hence Python on Linux.



