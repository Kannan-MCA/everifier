# Use an official OpenJDK 8 runtime as a parent image
FROM openjdk:8-jdk-alpine

# Set working directory in the container
WORKDIR /app

# Copy the executable jar file from the build context (target directory) to the container
COPY target/everifier-0.0.1-SNAPSHOT.jar app.jar

# Expose the port the application listens on
EXPOSE 8081

# Make sure the jar is executable (optional since java -jar executes the jar)
# RUN chmod +x app.jar

# Run the jar file
ENTRYPOINT ["java", "-jar", "app.jar"]
