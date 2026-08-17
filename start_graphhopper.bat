@echo off
echo Starting GraphHopper Routing Server on port 8989...
echo Using bundled Java 17 and pre-indexed graph-cache...

if exist ".\jdk17\jdk17.0.19_10\bin\java.exe" (
    ".\jdk17\jdk17.0.19_10\bin\java.exe" -Xmx4g -Xms2g -jar graphhopper-web-10.0.jar server config-example.yml
) else (
    java -Xmx4g -Xms2g -jar graphhopper-web-10.0.jar server config-example.yml
)
