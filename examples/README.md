# Kaspr Examples

This directory contains comprehensive examples demonstrating various Kaspr capabilities using generic, non-proprietary use cases. These examples showcase real-world patterns and best practices for building stream processing applications with Kaspr.

## Examples Overview

### 1. User Event Processor (`user-event-processor/`)
**Demonstrates:** Basic streaming data transformation, data validation, and enrichment

**Use Case:** Processing raw user events (login, logout, page views) by validating, enriching with metadata, and normalizing data formats.

**Key Features:**
- Data validation and error handling
- Metadata enrichment (session IDs, country mapping)
- Data normalization and standardization
- Dead letter queue for invalid events

**Files:**
- `app-user-events.yaml` - Application configuration
- `agent-event-enricher.yaml` - Event processing agent

### 2. Analytics Counter (`analytics-counter/`)
**Demonstrates:** Stateful operations, real-time counting, table operations, and lookups

**Use Case:** Real-time analytics system that maintains counters for various event dimensions and calculates user segments based on behavior patterns.

**Key Features:**
- Stateful counting across multiple dimensions
- User profile lookups and updates
- Time-windowed aggregations
- Dynamic user segmentation
- Performance optimizations with batch processing

**Files:**
- `app-analytics.yaml` - Application configuration
- `table-event-counters.yaml` - Counter storage table
- `table-user-profiles.yaml` - User profile storage
- `agent-counter-processor.yaml` - Counter processing agent

### 3. Analytics API (`analytics-api/`)
**Demonstrates:** WebView capabilities, REST API creation, table queries

**Use Case:** REST API that provides real-time access to analytics metrics stored in Kaspr tables.

**Key Features:**
- REST API endpoint creation with KasprWebView
- Dynamic query parameter parsing
- Table lookups and aggregations
- Error handling and response formatting
- Time range queries

**Files:**
- `app-analytics-api.yaml` - Application configuration
- `webview-metrics-dashboard.yaml` - REST API webview

### 4. User Enrichment (`user-enrichment/`)
**Demonstrates:** External API integration, caching, async operations

**Use Case:** Enriching user events with external data sources (geolocation, user profiles) while implementing smart caching to minimize API calls.

**Key Features:**
- Asynchronous external API calls
- Response caching with TTL
- Error handling and fallback strategies
- API rate limiting and timeout handling
- Multi-source data enrichment

**Files:**
- `app-user-enrichment.yaml` - Application configuration
- `table-api-cache.yaml` - API response cache table
- `agent-api-enricher.yaml` - API integration agent

### 5. Notification Router (`notification-router/`)
**Demonstrates:** Fan-out capabilities, complex routing logic, rate limiting

**Use Case:** Takes a single notification request and fans it out to multiple delivery channels (email, push, SMS, in-app) based on user preferences and rate limiting rules.

**Key Features:**
- Fan-out pattern (1 input → multiple outputs)
- User preference management
- Rate limiting with time windows
- Channel-specific message formatting
- Analytics tracking for deliveries
- Priority-based routing

**Files:**
- `app-notification-router.yaml` - Application configuration
- `table-user-preferences.yaml` - User preferences and rate limiting
- `agent-notification-fanout.yaml` - Fan-out processing agent

## Common Patterns Demonstrated

### Data Processing Patterns
- **Validation and Filtering**: Input data validation with error routing
- **Enrichment**: Adding computed fields and external data
- **Normalization**: Standardizing data formats
- **Transformation**: Converting between data structures

### Stateful Processing Patterns
- **Counters and Aggregations**: Real-time metrics calculation
- **Lookups**: Table-based data retrieval
- **Caching**: Performance optimization with TTL-based caching
- **State Management**: Maintaining user profiles and preferences

### Integration Patterns
- **External APIs**: HTTP API calls with error handling
- **REST Endpoints**: Exposing Kafka data via REST APIs
- **Multi-channel Output**: Fan-out to multiple destinations
- **Dead Letter Queues**: Error handling and recovery

### Performance Patterns
- **Batch Processing**: Processing multiple events together
- **Caching Strategies**: Reducing external API calls
- **Rate Limiting**: Protecting downstream systems
- **Resource Management**: Memory and CPU optimization

## Getting Started

1. **Deploy Prerequisites:**
   ```bash
   # Ensure Kafka cluster is available
   # Install Kaspr operator in your Kubernetes cluster
   ```

2. **Deploy an Example:**
   ```bash
   # Deploy the user event processor example
   kubectl apply -f examples-v2/user-event-processor/
   ```

3. **Send Test Data:**
   ```bash
   # Send sample events to the input topic
   # (Use your preferred Kafka producer tool)
   ```

4. **Monitor Results:**
   ```bash
   # Check output topics and application logs
   kubectl logs -f deployment/user-event-processor
   ```

## Data Flow

```
Raw Events → Event Enricher → Analytics Counter → API Dashboard
     ↓              ↓              ↓              ↑
Invalid Events   Enriched     Real-time      Query API
    (DLQ)        Events       Metrics       (WebView)
```

## Configuration

Each example includes environment variables for customization:

- **Resource limits**: Adjust CPU/memory based on your needs
- **Kafka settings**: Bootstrap servers, authentication
- **Application settings**: Timeouts, batch sizes, cache TTL
- **Business logic**: Rate limits, validation rules

## Extending the Examples

These examples serve as templates that you can customize for your specific use cases:

1. **Modify the Python logic** in the agent operations
2. **Adjust table schemas** for your data structures
3. **Add new input/output topics** as needed
4. **Implement additional external integrations**
5. **Customize error handling** and monitoring

## Production Considerations

When adapting these examples for production:

- **Security**: Implement proper authentication and authorization
- **Monitoring**: Add metrics and alerting
- **Scaling**: Adjust replica counts and resource limits
- **Data Retention**: Configure appropriate table retention policies
- **Error Handling**: Implement comprehensive error recovery strategies
- **Testing**: Add unit tests for your Python processing logic