"""
AI-powered features for GSuite CLI
"""

from .commands import ai
from .nlp import NaturalLanguageProcessor
from .analytics import AIAnalytics
from .summarizer import EmailSummarizer
from .query_engine import NaturalQueryEngine, ConversationContext
from .intent_schema import StructuredIntent, validate_structured_intent
from .date_parser import NaturalDateParser
from .tool_registry import (
    ToolDefinition,
    ToolRegistry,
    ToolValidator,
    ToolExecutor,
    ToolExecutionResult,
    get_default_registry,
)

__all__ = [
    'ai',
    'NaturalLanguageProcessor',
    'AIAnalytics',
    'EmailSummarizer',
    'NaturalQueryEngine',
    'ConversationContext',
    'StructuredIntent',
    'validate_structured_intent',
    'NaturalDateParser',
    'ToolDefinition',
    'ToolRegistry',
    'ToolValidator',
    'ToolExecutor',
    'ToolExecutionResult',
    'get_default_registry',
]

